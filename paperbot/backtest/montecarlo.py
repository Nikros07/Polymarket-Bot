"""
Monte-Carlo-Analyse und Robustheitsprüfung (Briefing §35, §38).

Ein Backtest liefert genau EINEN gezogenen Pfad. Er beantwortet "was ist
passiert?", nicht die eigentlich interessante Frage "wie schlimm hätte es
kommen können?". Genau diese Lücke schließt dieses Modul: die realisierte
Trade-Folge wird als Stichprobe aus einer Verteilung behandelt und tausendfach
neu gezogen.

Drei Dinge werden dabei sichtbar, die im Einzelbacktest unsichtbar bleiben:

  SEQUENZRISIKO. Dieselben Trades in anderer Reihenfolge ergeben denselben
  Endwert nur im additiven Modell. Multiplikativ — und real ist es
  multiplikativ — entscheidet die Reihenfolge über den maximalen Drawdown und
  damit darüber, ob das Konto die Strecke überhaupt durchhält.

  VERTEILUNG STATT PUNKTSCHÄTZUNG. Ein realisierter Max-Drawdown von 12% sagt
  nichts darüber, ob das der Normalfall war oder das glückliche Ende. Erst
  Median, p95 und Worst-Case über viele Pfade machen daraus eine Risikoaussage.

  RUIN. Kapital ist nach unten bei null begrenzt, und ein Konto, das auf die
  Hälfte fällt, wird real meist abgeschaltet. Eine reine
  Erwartungswert-Rechnung ignoriert beides.

Was Monte Carlo NICHT kann: aus einer schlechten Stichprobe eine gute Aussage
machen. Alle Verfahren hier ziehen aus den beobachteten Trades — enthält der
Backtest keinen echten Crash, enthält ihn auch keiner der simulierten Pfade.
Die Ergebnisse sind eine Untergrenze für das Risiko, keine Obergrenze.

Alles hier ist reine Rechnung: kein I/O, kein Netz, jeder Zufall über einen
explizit übergebenen `seed` reproduzierbar (Briefing §45).

Kopiert aus NEMI backtest/montecarlo.py (2026-10-22); für Binärwetten: Gewinn-R = (1 - Preis) / Preis, Verlust-R = -1.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

# Defaults aus der NEMI-Projektkonfiguration (nemi/config.py), als Konstanten
# kopiert, damit das Modul nur von numpy abhängt:
#   PortfolioConfig.starting_capital_eur = 1_000.0  (nemi/config.py, PortfolioConfig)
#   BALANCED.risk_per_trade = 0.010                 (nemi/config.py, BALANCED)
# Bewusst als Modulkonstanten und nicht als Live-Zugriff: eine Analyse muss
# über ihre Laufzeit stabile Annahmen haben.
DEFAULT_STARTING_CAPITAL: float = 1_000.0
DEFAULT_RISK_PER_TRADE: float = 0.010

DEFAULT_N_PATHS: int = 10_000

# Schwellen für "Drawdown schlimmer als X". 20% tut weh, 30% ist der Bereich,
# ab dem die meisten Systeme abgeschaltet werden, 50% erfordert +100% zur
# Erholung — deshalb ist genau das auch die Default-Ruinschwelle.
DEFAULT_DRAWDOWN_THRESHOLDS: tuple[float, ...] = (0.10, 0.20, 0.30, 0.50)
DEFAULT_RUIN_THRESHOLD: float = 0.50

# Unter dieser Anzahl beobachteter Trades ist Resampling Selbstbetrug: man
# zieht dann im Wesentlichen die Zufälligkeit der eigenen Mini-Stichprobe
# nach. Statt zu werfen liefert `analyse` in dem Fall ein leeres Ergebnis mit
# Begründung — ein stiller Fehlwert wäre genau die Silent-Failure-Sorte, die
# Briefing §47 verbietet.
MIN_TRADES_FOR_ANALYSIS: int = 10

RESAMPLE_METHODS: tuple[str, ...] = ("bootstrap", "block", "shuffle")


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _clean_r(r_multiples: Sequence[float] | np.ndarray) -> np.ndarray:
    """
    R-Vielfache als flaches float-Array, ohne NaN/inf.

    Nicht-endliche Werte werden entfernt und nicht durch 0 ersetzt: ein
    fabrizierter Trade mit R=0 sähe wie ein realer Break-Even-Trade aus und
    würde Erwartungswert und Verluststrecken verfälschen.
    """
    arr = np.asarray(r_multiples, dtype=float).ravel()
    return arr[np.isfinite(arr)]


def _pct(values: np.ndarray, q: float) -> float:
    """Perzentil als float, robust gegen leere Arrays."""
    if values.size == 0:
        return float("nan")
    return float(np.percentile(values, q))


# ─── Resampling ──────────────────────────────────────────────────────────────

def resample_trades(
    r_multiples: Sequence[float] | np.ndarray,
    n_paths: int,
    path_length: int | None = None,
    method: str = "bootstrap",
    seed: int | None = None,
    block_size: int | None = None,
) -> np.ndarray:
    """
    Ziehe `n_paths` alternative Trade-Folgen aus den beobachteten R-Vielfachen.

    Rückgabe: Array der Form (n_paths, path_length) mit R-Vielfachen.
    `path_length` ist per Default die Länge der Eingabe — dann simuliert man
    "dieselbe Historie, anders gewürfelt".

    Die drei Methoden beantworten unterschiedliche Fragen und sind deshalb
    nicht austauschbar:

    "bootstrap" — Ziehen MIT Zurücklegen.
        Zerstört die Reihenfolge vollständig und lässt einzelne Trades mehrfach
        auftreten. Das ist der Standardtest auf Sequenzrisiko: wie viel des
        Backtest-Ergebnisses hing daran, dass die Gewinner zufällig früh kamen?
        Annahme: Trades sind unabhängig und identisch verteilt.

    "block" — Block-Bootstrap, zieht zusammenhängende Blöcke der Länge
        `block_size` (mit Zurücklegen, zirkulär über das Ende hinaus).
        Die i.i.d.-Annahme des einfachen Bootstraps ist bei Trades meist falsch:
        Ergebnisse treten in REGIME-CLUSTERN auf. Ein Trendfolgesystem gewinnt
        in trendenden Märkten und verliert in Seitwärtsphasen — Gewinne und
        Verluste kommen also gehäuft, nicht gemischt. Genau diese Häufung
        erzeugt die tiefen Drawdowns, und der einfache Bootstrap mischt sie
        weg. Er unterschätzt das Risiko dann systematisch. Der Block-Bootstrap
        erhält Autokorrelation bis zur Blocklänge und liefert damit die
        ehrlichere Drawdown-Verteilung; die Blocklänge ist die Annahme darüber,
        wie lang ein Regime im Schnitt anhält.
        Zirkulär, weil bei nicht-zirkulären Blöcken die Trades am Rand seltener
        gezogen werden als die in der Mitte — das verzerrt den Mittelwert.

    "shuffle" — Permutation OHNE Zurücklegen.
        Exakt dieselben Trades, nur in anderer Reihenfolge. Endwert im
        additiven Modell identisch, im multiplikativen nicht — die Differenz
        ist reines Sequenzrisiko, ohne jede Stichprobenunsicherheit. Damit ist
        `path_length` hier zwangsläufig auf die Anzahl beobachteter Trades
        begrenzt.

    Ein Seed macht das Ergebnis exakt reproduzierbar (Briefing §45).
    """
    if method not in RESAMPLE_METHODS:
        raise ValueError(f"unbekannte Methode {method!r}, erlaubt: {RESAMPLE_METHODS}")
    if n_paths < 1:
        raise ValueError("n_paths muss >= 1 sein")

    r = _clean_r(r_multiples)
    n = r.size

    length = n if path_length is None else int(path_length)
    if length < 0:
        raise ValueError("path_length darf nicht negativ sein")

    # Ohne Trades gibt es nichts zu ziehen. Leeres Ergebnis mit korrekter Form,
    # damit die Aufrufer nicht auf None prüfen müssen.
    if n == 0 or length == 0:
        return np.empty((n_paths, 0), dtype=float)

    rng = np.random.default_rng(seed)

    if method == "bootstrap":
        idx = rng.integers(0, n, size=(n_paths, length))

    elif method == "shuffle":
        if length > n:
            raise ValueError(
                "shuffle zieht ohne Zurücklegen: path_length "
                f"({length}) darf die Trade-Anzahl ({n}) nicht überschreiten"
            )
        # Eine Permutation je Pfad in einem Rutsch: argsort auf Zufallszahlen
        # ist äquivalent zu n_paths einzelnen Permutationen, aber vektorisiert.
        idx = np.argsort(rng.random((n_paths, n)), axis=1)[:, :length]

    else:  # "block"
        size = _default_block_size(n) if block_size is None else int(block_size)
        if size < 1:
            raise ValueError("block_size muss >= 1 sein")
        size = min(size, n)

        n_blocks = int(np.ceil(length / size))
        starts = rng.integers(0, n, size=(n_paths, n_blocks))
        offsets = np.arange(size)
        # Modulo = zirkulär: ein Block, der hinten überläuft, wird vorne
        # fortgesetzt. Jeder Trade ist damit gleich wahrscheinlich Blockstart.
        idx = (starts[:, :, None] + offsets[None, None, :]) % n
        idx = idx.reshape(n_paths, n_blocks * size)[:, :length]

    return r[idx]


def _default_block_size(n: int) -> int:
    """
    Heuristische Blocklänge: ~sqrt(n).

    Es gibt keine "richtige" Blocklänge ohne Annahme über die
    Regime-Persistenz. sqrt(n) ist die übliche Faustregel und hält die Balance:
    lang genug, um Cluster zu erhalten, kurz genug, um noch echte
    Neuziehungen zu erzeugen statt die Originalfolge zu kopieren.
    """
    return max(1, int(round(np.sqrt(n))))


# ─── Equity-Pfade ────────────────────────────────────────────────────────────

def simulate_equity(
    paths_r: np.ndarray,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
) -> np.ndarray:
    """
    Baue Equity-Pfade aus R-Vielfachen — MULTIPLIKATIV.

    Rückgabe: Array der Form (n_paths, n_trades + 1); Spalte 0 ist das
    Startkapital, damit ein Drawdown ab dem ersten Trade messbar ist.

    Das Modell ist bewusst multiplikativ:

        equity_t+1 = equity_t * (1 + risk_per_trade * R_t)

    Bei prozentualem Risiko pro Trade hängt der riskierte EUR-Betrag am
    AKTUELLEN Kapital. Ein additives Modell (fester EUR-Betrag je R) ist in
    beide Richtungen falsch: es überschätzt Verluste, weil es nach einem
    Rückschlag weiter die alte, zu große Positionsgröße unterstellt, und es
    unterschätzt Gewinne, weil der Zinseszins fehlt. Für die Kernfrage dieses
    Moduls — wie tief geht der Drawdown, droht Ruin — ist der Unterschied
    entscheidend: multiplikativ kann das Kapital asymptotisch gegen null gehen,
    aber es wird nie negativ.

    Der Faktor wird bei 0 abgeschnitten. Ein R schlechter als
    -1/risk_per_trade (z.B. ein Gap durch den Stop hindurch, das mehr als das
    geplante Risiko kostet) würde sonst negatives Kapital erzeugen. Praktisch
    ist das der Totalverlust: das Konto bleibt danach bei 0 und erholt sich
    nicht mehr — genau das Verhalten einer absorbierenden Ruinschranke.
    """
    if starting_capital <= 0:
        raise ValueError("starting_capital muss > 0 sein")
    if not 0 < risk_per_trade <= 1.0:
        raise ValueError("risk_per_trade muss in (0, 1] liegen")

    paths = np.atleast_2d(np.asarray(paths_r, dtype=float))

    factors = 1.0 + risk_per_trade * paths
    np.clip(factors, 0.0, None, out=factors)

    equity = starting_capital * np.cumprod(factors, axis=1)
    start_col = np.full((paths.shape[0], 1), float(starting_capital))
    return np.hstack([start_col, equity])


def max_drawdowns(equity_paths: np.ndarray) -> np.ndarray:
    """
    Maximaler relativer Drawdown je Pfad, als Anteil (0.25 = -25%).

    Gemessen gegen das laufende Hoch (Peak-to-Trough), nicht gegen das
    Startkapital — ein System, das erst +80% macht und dann auf +20% zurückfällt,
    hat einen realen 33%-Drawdown durchlebt, auch wenn es nie unter Start lag.
    """
    eq = np.atleast_2d(np.asarray(equity_paths, dtype=float))
    if eq.shape[1] == 0:
        return np.zeros(eq.shape[0])
    peaks = np.maximum.accumulate(eq, axis=1)
    dd = np.where(peaks > 0, 1.0 - eq / np.where(peaks > 0, peaks, 1.0), 1.0)
    return dd.max(axis=1)


def longest_losing_streaks(paths_r: np.ndarray) -> np.ndarray:
    """
    Längste Serie aufeinanderfolgender Verlust-Trades je Pfad.

    Die psychologisch teuerste Kennzahl des ganzen Moduls: Systeme werden
    selten wegen des Drawdowns abgeschaltet, sondern weil elf Verlierer in
    Folge wie ein kaputtes System aussehen. Wer vorher weiß, dass p95 bei
    zwölf liegt, hält durch.
    """
    losses = np.atleast_2d(np.asarray(paths_r, dtype=float)) < 0.0
    n_paths, n_trades = losses.shape

    best = np.zeros(n_paths, dtype=int)
    current = np.zeros(n_paths, dtype=int)
    # Schleife über die Trades (kurz), vektorisiert über die Pfade (viele).
    for j in range(n_trades):
        current = np.where(losses[:, j], current + 1, 0)
        np.maximum(best, current, out=best)
    return best


def recovery_times(equity_paths: np.ndarray) -> np.ndarray:
    """
    Trades vom Tiefpunkt des tiefsten Drawdowns bis zurück auf das alte Hoch.

    NaN, wenn der Pfad sich bis zum Ende nicht erholt hat — das ist eine
    eigene, wichtige Aussage und darf nicht als "0" oder als Pfadlänge
    getarnt werden.

    Gemessen wird ab dem Tief, nicht ab dem Peak. Der Weg nach unten ist
    Drawdown, der Weg zurück ist Erholung; nur letztere beantwortet die Frage
    "wie lange muss ich das aushalten, nachdem es am schlimmsten war?".
    """
    eq = np.atleast_2d(np.asarray(equity_paths, dtype=float))
    n_paths, n_cols = eq.shape
    if n_cols < 2:
        return np.zeros(n_paths)

    peaks = np.maximum.accumulate(eq, axis=1)
    dd = np.where(peaks > 0, 1.0 - eq / np.where(peaks > 0, peaks, 1.0), 1.0)

    trough = dd.argmax(axis=1)
    rows = np.arange(n_paths)
    peak_value = peaks[rows, trough]

    positions = np.arange(n_cols)
    # Erholung zählt nur nach dem Tief; das Hoch selbst liegt davor.
    recovered = (eq >= peak_value[:, None]) & (positions[None, :] > trough[:, None])
    has_recovery = recovered.any(axis=1)
    first = np.where(has_recovery, recovered.argmax(axis=1), 0)

    out = np.where(has_recovery, (first - trough).astype(float), np.nan)
    # Ein Pfad ohne jeden Drawdown hat auch keine Erholungszeit.
    return np.where(dd.max(axis=1) <= 0.0, 0.0, out)


# ─── Ergebnis ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MonteCarloResult:
    """
    Ergebnis einer Monte-Carlo-Analyse.

    Alle Kennzahlen sind optional: bei leerer oder zu kurzer Eingabe liefert
    `analyse` ein Objekt mit `ok=False`, gefüllter `reason` und None-Feldern,
    statt zu werfen. Der Aufrufer bekommt so eine Antwort, die er weiterreichen
    kann — und keine, die er versehentlich als Zahl verwendet.
    """
    ok: bool
    reason: str | None = None

    # Setup
    method: str = "bootstrap"
    n_paths: int = 0
    n_trades: int = 0
    observed_trades: int = 0
    starting_capital: float = 0.0
    risk_per_trade: float = 0.0
    seed: int | None = None
    mean_r: float | None = None

    # Endkapital
    final_median: float | None = None
    final_p5: float | None = None
    final_p25: float | None = None
    final_p75: float | None = None
    final_p95: float | None = None
    profitable_rate: float | None = None

    # Maximaler Drawdown (Anteile, 0.25 = -25%)
    max_dd_median: float | None = None
    max_dd_p95: float | None = None
    max_dd_worst: float | None = None
    prob_drawdown_exceeds: dict[float, float] | None = None

    # Ruin
    ruin_threshold: float | None = None
    prob_ruin: float | None = None

    # Verluststrecken (Trades)
    losing_streak_median: float | None = None
    losing_streak_p95: float | None = None
    losing_streak_worst: int | None = None

    # Erholung aus dem tiefsten Drawdown (Trades)
    recovery_median: float | None = None
    recovery_p95: float | None = None
    recovery_worst: float | None = None
    unrecovered_rate: float | None = None


def analyse(
    r_multiples: Sequence[float] | np.ndarray,
    n_paths: int = DEFAULT_N_PATHS,
    path_length: int | None = None,
    method: str = "bootstrap",
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
    drawdown_thresholds: Sequence[float] = DEFAULT_DRAWDOWN_THRESHOLDS,
    ruin_threshold: float = DEFAULT_RUIN_THRESHOLD,
    min_trades: int = MIN_TRADES_FOR_ANALYSIS,
    seed: int | None = None,
    block_size: int | None = None,
) -> MonteCarloResult:
    """
    Vollständige Monte-Carlo-Analyse einer Trade-Folge.

    `ruin_threshold` ist der Anteil des Startkapitals, dessen Unterschreiten
    als Ruin gilt (0.5 = die Hälfte weg). Gezählt wird BERÜHRUNG, nicht der
    Endstand: wer zwischenzeitlich auf 40% fällt, hat real längst abgeschaltet,
    auch wenn der Pfad rechnerisch zurückkommt.

    Zu wenige Trades führen nicht zu einer Exception, sondern zu
    `ok=False` mit Begründung.
    """
    r = _clean_r(r_multiples)
    length = r.size if path_length is None else int(path_length)

    if r.size < min_trades:
        return MonteCarloResult(
            ok=False,
            reason=(
                f"nur {r.size} verwertbare Trades, mindestens {min_trades} nötig — "
                "Resampling würde hier vor allem die eigene Stichprobenzufälligkeit "
                "reproduzieren"
            ),
            method=method,
            observed_trades=int(r.size),
            starting_capital=float(starting_capital),
            risk_per_trade=float(risk_per_trade),
            seed=seed,
        )
    if length < 1:
        return MonteCarloResult(
            ok=False,
            reason="path_length < 1 — es gibt nichts zu simulieren",
            method=method,
            observed_trades=int(r.size),
            starting_capital=float(starting_capital),
            risk_per_trade=float(risk_per_trade),
            seed=seed,
        )

    paths_r = resample_trades(
        r, n_paths=n_paths, path_length=length, method=method,
        seed=seed, block_size=block_size,
    )
    equity = simulate_equity(paths_r, starting_capital, risk_per_trade)

    final = equity[:, -1]
    dd = max_drawdowns(equity)
    streaks = longest_losing_streaks(paths_r)
    recovery = recovery_times(equity)

    # Ruin über das Pfadminimum, nicht über den Endstand — siehe Docstring.
    ruin_level = ruin_threshold * starting_capital
    prob_ruin = float(np.mean(equity.min(axis=1) <= ruin_level))

    finite_recovery = recovery[np.isfinite(recovery)]
    unrecovered = float(np.mean(~np.isfinite(recovery)))

    return MonteCarloResult(
        ok=True,
        method=method,
        n_paths=int(n_paths),
        n_trades=int(length),
        observed_trades=int(r.size),
        starting_capital=float(starting_capital),
        risk_per_trade=float(risk_per_trade),
        seed=seed,
        mean_r=float(r.mean()),

        final_median=_pct(final, 50),
        final_p5=_pct(final, 5),
        final_p25=_pct(final, 25),
        final_p75=_pct(final, 75),
        final_p95=_pct(final, 95),
        profitable_rate=float(np.mean(final > starting_capital)),

        max_dd_median=_pct(dd, 50),
        max_dd_p95=_pct(dd, 95),
        max_dd_worst=float(dd.max()),
        prob_drawdown_exceeds={
            float(t): float(np.mean(dd > t)) for t in drawdown_thresholds
        },

        ruin_threshold=float(ruin_threshold),
        prob_ruin=prob_ruin,

        losing_streak_median=_pct(streaks.astype(float), 50),
        losing_streak_p95=_pct(streaks.astype(float), 95),
        losing_streak_worst=int(streaks.max()),

        recovery_median=_pct(finite_recovery, 50) if finite_recovery.size else None,
        recovery_p95=_pct(finite_recovery, 95) if finite_recovery.size else None,
        recovery_worst=float(finite_recovery.max()) if finite_recovery.size else None,
        unrecovered_rate=unrecovered,
    )


# ─── Ruinrisiko ──────────────────────────────────────────────────────────────

def risk_of_ruin(
    win_rate: float,
    avg_win_r: float,
    avg_loss_r: float,
    risk_per_trade: float,
    ruin_threshold: float = DEFAULT_RUIN_THRESHOLD,
    n_trades: int = 200,
    n_paths: int = 5_000,
    method: str = "simulation",
    seed: int | None = None,
) -> float:
    """
    Wahrscheinlichkeit, das Kapital unter `ruin_threshold` des Startwerts zu
    drücken. Rückgabe in [0, 1].

    `avg_loss_r` wird als Betrag gelesen: 1.0 und -1.0 bedeuten dasselbe.

    ANNAHMEN, die für beide Verfahren gelten:
      - Es gibt genau zwei Ausgänge je Trade (avg_win_r / -avg_loss_r). Reale
        Verteilungen haben Ränder; wer die kennt, sollte `analyse` auf die
        echten R-Vielfachen anwenden statt diese Näherung zu benutzen.
      - Trades sind unabhängig. Bei Regime-Clustern ist das zu optimistisch —
        vgl. den Block-Bootstrap in `resample_trades`.
      - `win_rate`, `avg_win_r` und `avg_loss_r` sind stabil. Genau das sind
        sie in einem Regimewechsel nicht.

    method="simulation" (Default)
        Simuliert `n_paths` Pfade multiplikativ über `n_trades` Trades und
        zählt, wie viele die Schwelle berühren. Konsistent mit
        `simulate_equity`, also inklusive Positionsgrößen-Anpassung an das
        laufende Kapital — dadurch ist Ruin schwerer zu erreichen als im
        additiven Modell, denn nach Verlusten wird automatisch kleiner
        riskiert. Endlicher Horizont: das Ergebnis ist die Ruinwahrscheinlichkeit
        INNERHALB von n_trades, nicht "irgendwann".

    method="analytic"
        Klassische Lundberg-Näherung für den unendlichen Horizont. Rechnet in
        R-Einheiten mit FESTER Einsatzgröße (additiv), das Konto hat
        U = ruin_verlust / risk_per_trade Einheiten Puffer. Gesucht ist die
        Wurzel z in (0,1) von p*z^a + q*z^(-b) = 1, dann gilt
        Ruinrisiko ≈ z^U. Bei nicht-positivem Erwartungswert ist der Ruin bei
        unendlichem Horizont sicher, das Verfahren liefert dann 1.0.
        Die Näherung ist konservativer als die Simulation — kein Zinseszins,
        keine Risikoreduktion nach Verlusten, unbegrenzte Zeit.
    """
    if not 0.0 <= win_rate <= 1.0:
        raise ValueError("win_rate muss in [0, 1] liegen")
    if not 0 < risk_per_trade <= 1.0:
        raise ValueError("risk_per_trade muss in (0, 1] liegen")
    if not 0.0 <= ruin_threshold < 1.0:
        raise ValueError("ruin_threshold muss in [0, 1) liegen")

    win_r = float(avg_win_r)
    loss_r = abs(float(avg_loss_r))
    if win_r <= 0 or loss_r <= 0:
        raise ValueError("avg_win_r und avg_loss_r müssen von null verschieden sein")

    if method == "analytic":
        # Verlust bis zum Ruin, umgerechnet in R-Einheiten.
        units = (1.0 - ruin_threshold) / risk_per_trade
        return _analytic_risk_of_ruin(win_rate, win_r, loss_r, units)

    if method != "simulation":
        raise ValueError(f"unbekannte Methode {method!r}, erlaubt: simulation, analytic")

    if n_trades < 1 or n_paths < 1:
        raise ValueError("n_trades und n_paths müssen >= 1 sein")

    rng = np.random.default_rng(seed)
    wins = rng.random((n_paths, n_trades)) < win_rate
    paths_r = np.where(wins, win_r, -loss_r)

    # Startkapital 1.0: die Schwelle ist dann direkt der Anteil.
    equity = simulate_equity(paths_r, 1.0, risk_per_trade)
    return float(np.mean(equity.min(axis=1) <= ruin_threshold))


def _analytic_risk_of_ruin(p: float, a: float, b: float, units: float) -> float:
    """
    Lundberg-Wurzel per Bisektion, siehe `risk_of_ruin`.

    Kontrolle: für a = b = 1 reduziert sich z auf q/p, also auf die
    Lehrbuchformel Ruinrisiko = (q/p)^U.
    """
    q = 1.0 - p
    if p >= 1.0:
        return 0.0
    if p <= 0.0:
        return 1.0
    # Ohne positiven Erwartungswert ist der Ruin bei unendlichem Horizont sicher.
    if p * a - q * b <= 0.0:
        return 1.0

    def g(z: float) -> float:
        return p * z ** a + q * z ** (-b) - 1.0

    # g(0+) -> +inf, g(1-) < 0 (weil die Ableitung in 1 gleich dem
    # Erwartungswert und damit positiv ist) — die Wurzel liegt dazwischen.
    lo, hi = 1e-12, 1.0 - 1e-9
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if g(mid) > 0.0:
            lo = mid
        else:
            hi = mid

    z = 0.5 * (lo + hi)
    return float(min(1.0, max(0.0, z ** units)))


# ─── Parameter-Sensitivität ──────────────────────────────────────────────────

def parameter_sensitivity(
    results: Mapping[float, float],
    higher_is_better: bool = True,
    tolerance: float = 0.20,
    min_plateau_points: int = 3,
    min_plateau_fraction: float = 0.25,
    flat_tolerance: float = 0.02,
) -> dict:
    """
    Bewerte einen Parameter-Sweep auf STABILE REGION vs. ISOLIERTER AUSREISSER
    (Briefing §39).

    `results` bildet Parameterwert -> Kennzahl ab (z.B. ATR-Multiplikator ->
    Sharpe). `higher_is_better=False` dreht die Richtung um, etwa für
    Drawdowns.

    Warum das die eigentliche Optimierungsfrage ist: 1.4/1.5/1.6/1.7 alle gut
    ist überzeugender als 1.637 grandios und 1.638 katastrophal. Der isolierte
    Spitzenwert ist fast immer Rauschen, das die Optimierung eingesammelt hat —
    er wird sich out-of-sample nicht wiederholen, weil die nächste Stichprobe
    ihr Rauschen an einer anderen Stelle hat. Ein Plateau dagegen heißt: das
    System funktioniert wegen seiner Logik, nicht wegen dieses einen Wertes.

    Gemessen wird beides:

      PLATEAU-BREITE. Ausgehend vom Optimum wird nach links und rechts
      gelaufen, solange die Kennzahl innerhalb von `tolerance * scale` des
      Optimums bleibt (`scale` = max(|Optimum|, Spannweite), damit auch
      negative Kennzahlen und Nullpunkte sauber behandelt werden). Ergebnis:
      Anzahl Stützstellen, Breite in Parametereinheiten und Anteil am
      gesamten gesweepten Bereich. Nur ein ZUSAMMENHÄNGENDER Bereich um das
      Optimum zählt — verstreute gute Einzelwerte sind kein Plateau.

      NACHBARSCHAFTS-ABFALL. Wie stark fallen die direkten Nachbarn des
      Optimums ab, relativ zu `scale`. Ein Wert nahe 0 heißt "die Nachbarn
      können es auch", nahe 1 heißt "der Peak steht allein".

    Urteil (`verdict`):
      "stable_plateau"    — genug Stützstellen UND genug Breite: benutzbar.
      "narrow_plateau"    — nur zwei Punkte oder ein sehr schmaler Bereich:
                            verwendbar, aber mit Vorsicht und engem Monitoring.
      "isolated_peak"     — das Optimum steht allein. Nicht verwenden; besser
                            den Mittelwert einer stabilen Region nehmen.
      "insufficient_data" — unter drei Stützstellen ist keine Aussage möglich.

    `robust_value` ist der empfohlene Parameter: die Mitte des Plateaus, nicht
    dessen Spitze. Bei einem Plateau liegt man dort am weitesten von beiden
    Abbruchkanten entfernt.

    `is_flat` markiert den Sonderfall, dass die Kennzahl über den gesamten
    Sweep praktisch nicht reagiert. Das ist kein Robustheitsbeweis, sondern
    heißt meistens, dass der Parameter nichts tut oder der Sweep zu eng war.
    """
    pairs = sorted(
        (float(k), float(v))
        for k, v in results.items()
        if np.isfinite(float(k)) and np.isfinite(float(v))
    )
    n = len(pairs)

    out: dict = {
        "n_points": n,
        "verdict": "insufficient_data",
        "explanation": "",
        "best_value": None,
        "best_metric": None,
        "worst_metric": None,
        "threshold": None,
        "relative_spread": None,
        "is_flat": None,
        "plateau_values": (),
        "plateau_points": 0,
        "plateau_bounds": None,
        "plateau_width": None,
        "plateau_fraction": None,
        "neighbour_values": (),
        "neighbour_drop": None,
        "neighbour_dispersion": None,
        "robust_value": None,
    }

    if n < 3:
        out["explanation"] = (
            f"nur {n} Stützstellen — Plateau und Ausreißer sind daran nicht "
            "unterscheidbar, mindestens 3 nötig"
        )
        if n:
            best_i = max(range(n), key=lambda i: pairs[i][1] if higher_is_better else -pairs[i][1])
            out["best_value"], out["best_metric"] = pairs[best_i]
        return out

    params = np.array([p for p, _ in pairs], dtype=float)
    metrics = np.array([m for _, m in pairs], dtype=float)
    # Intern wird immer maximiert; die Orientierung wird einmal vorne gedreht.
    oriented = metrics if higher_is_better else -metrics

    best_idx = int(np.argmax(oriented))
    best_o = float(oriented[best_idx])
    spread = float(best_o - oriented.min())

    # Bezugsgröße für "wie viel ist viel". max(|Optimum|, Spannweite) hält die
    # Aussage auch bei Kennzahlen um null oder mit negativem Optimum sinnvoll.
    scale = max(abs(best_o), spread)
    degenerate = scale <= 1e-12

    relative_spread = 0.0 if degenerate else spread / scale
    is_flat = relative_spread < flat_tolerance

    threshold_o = best_o if degenerate else best_o - tolerance * scale
    qualifies = oriented >= threshold_o - 1e-12

    # Zusammenhängender Lauf um das Optimum.
    lo = best_idx
    while lo - 1 >= 0 and qualifies[lo - 1]:
        lo -= 1
    hi = best_idx
    while hi + 1 < n and qualifies[hi + 1]:
        hi += 1

    plateau_points = hi - lo + 1
    plateau_width = float(params[hi] - params[lo])
    total_width = float(params[-1] - params[0])
    plateau_fraction = (
        plateau_width / total_width if total_width > 0 else plateau_points / n
    )

    neighbours = [i for i in (best_idx - 1, best_idx + 1) if 0 <= i < n]
    neighbour_o = oriented[neighbours]
    if degenerate:
        neighbour_drop = 0.0
        neighbour_dispersion = 0.0
    else:
        neighbour_drop = float(np.mean((best_o - neighbour_o) / scale))
        neighbour_dispersion = (
            float(np.std(neighbour_o) / scale) if len(neighbours) > 1 else 0.0
        )

    centre = 0.5 * (params[lo] + params[hi])
    robust_idx = lo + int(np.argmin(np.abs(params[lo:hi + 1] - centre)))

    if plateau_points >= min_plateau_points and plateau_fraction >= min_plateau_fraction:
        verdict = "stable_plateau"
        explanation = (
            f"{plateau_points} benachbarte Werte von {params[lo]:g} bis {params[hi]:g} "
            f"bleiben innerhalb von {tolerance:.0%} des Optimums "
            f"({plateau_fraction:.0%} des Sweeps) — die Kennzahl hängt an der Logik, "
            f"nicht am Einzelwert. Empfehlung: Plateaumitte {params[robust_idx]:g}."
        )
    elif plateau_points >= 2:
        verdict = "narrow_plateau"
        explanation = (
            f"nur {plateau_points} benachbarte Werte tragen das Optimum "
            f"({plateau_width:g} von {total_width:g} Parameterbreite). Schmal genug, "
            "um zufällig zu sein — nur mit engem Monitoring verwenden."
        )
    else:
        verdict = "isolated_peak"
        explanation = (
            f"das Optimum bei {params[best_idx]:g} steht allein; die direkten Nachbarn "
            f"fallen im Mittel um {neighbour_drop:.0%} der Skala ab. Klassischer "
            "Overfitting-Fund — out-of-sample ist davon nichts zu erwarten."
        )

    if is_flat:
        explanation += (
            f" Hinweis: die Kennzahl schwankt über den gesamten Sweep nur um "
            f"{relative_spread:.1%} — der Parameter bewegt hier faktisch nichts, "
            "oder der Sweep ist zu eng gewählt."
        )

    out.update(
        verdict=verdict,
        explanation=explanation,
        best_value=float(params[best_idx]),
        best_metric=float(metrics[best_idx]),
        worst_metric=float(metrics.min() if higher_is_better else metrics.max()),
        threshold=float(threshold_o if higher_is_better else -threshold_o),
        relative_spread=relative_spread,
        is_flat=bool(is_flat),
        plateau_values=tuple(float(p) for p in params[lo:hi + 1]),
        plateau_points=int(plateau_points),
        plateau_bounds=(float(params[lo]), float(params[hi])),
        plateau_width=plateau_width,
        plateau_fraction=float(plateau_fraction),
        neighbour_values=tuple(float(params[i]) for i in neighbours),
        neighbour_drop=neighbour_drop,
        neighbour_dispersion=neighbour_dispersion,
        robust_value=float(params[robust_idx]),
    )
    return out


# ─── Ausgabe ─────────────────────────────────────────────────────────────────

def summary(result: MonteCarloResult) -> str:
    """
    Lesbare Zusammenfassung einer Monte-Carlo-Analyse.

    Reine Formatierung, kein I/O — der Aufrufer entscheidet, wohin der Text
    geht.
    """
    if not result.ok:
        return (
            "Monte-Carlo: keine Analyse möglich\n"
            f"  Grund: {result.reason}"
        )

    cap = result.starting_capital
    lines: list[str] = []

    lines.append(
        f"Monte-Carlo — {result.n_paths:,} Pfade x {result.n_trades} Trades "
        f"({result.method}, Seed {result.seed})"
    )
    lines.append(
        f"Basis: {result.observed_trades} beobachtete Trades, "
        f"Mittelwert {result.mean_r:+.3f}R | "
        f"Start {cap:,.0f} EUR | Risiko/Trade {result.risk_per_trade:.2%}"
    )
    lines.append("-" * 68)

    lines.append("Endkapital (EUR)")
    lines.append(
        f"  p5 {result.final_p5:>12,.0f} | p25 {result.final_p25:>12,.0f} | "
        f"Median {result.final_median:>12,.0f}"
    )
    lines.append(
        f"  p75 {result.final_p75:>11,.0f} | p95 {result.final_p95:>12,.0f} | "
        f"profitabel {result.profitable_rate:>8.1%}"
    )

    lines.append("Maximaler Drawdown")
    lines.append(
        f"  Median {result.max_dd_median:>7.1%} | p95 {result.max_dd_p95:>7.1%} | "
        f"Worst {result.max_dd_worst:>7.1%}"
    )
    if result.prob_drawdown_exceeds:
        probs = " | ".join(
            f">{t:.0%}: {p:.1%}"
            for t, p in sorted(result.prob_drawdown_exceeds.items())
        )
        lines.append(f"  {probs}")

    lines.append(
        f"Ruinrisiko (unter {result.ruin_threshold:.0%} des Startkapitals): "
        f"{result.prob_ruin:.2%}"
    )

    lines.append("Längste Verluststrecke (Trades)")
    lines.append(
        f"  Median {result.losing_streak_median:>5.0f} | "
        f"p95 {result.losing_streak_p95:>5.0f} | "
        f"Worst {result.losing_streak_worst:>5d}"
    )

    lines.append("Erholung aus dem tiefsten Drawdown (Trades)")
    if result.recovery_median is None:
        lines.append("  kein Pfad hat sich innerhalb des Horizonts erholt")
    else:
        lines.append(
            f"  Median {result.recovery_median:>5.0f} | "
            f"p95 {result.recovery_p95:>5.0f} | "
            f"nicht erholt {result.unrecovered_rate:>6.1%}"
        )

    return "\n".join(lines)
