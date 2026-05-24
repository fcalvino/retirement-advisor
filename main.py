"""
Retirement Advisor — CLI entry point.

Usage:
    python main.py analyze AAPL
    python main.py analyze AAPL MSFT GOOGL
    python main.py screen
    python main.py portfolio
    python main.py dashboard          # launches Streamlit
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import argparse

from loguru import logger

from analysis.strategy import full_analysis
from config import DEFAULT_TICKERS
from portfolio.tracker import Portfolio


def cmd_analyze(symbols: list[str]) -> None:
    """Full analysis for one or more tickers."""
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"  {symbol}")
        print(f"{'='*60}")

        fund, tech, decision = full_analysis(symbol)

        print(f"\n  {fund.company_name} | {fund.sector}")
        print(f"  Price: ${fund.current_price:.2f}  |  Market Cap: ${fund.market_cap/1e9:.1f}B")
        print(f"\n  ► DECISION: {decision.action_emoji} {decision.action}  ({decision.confidence} confidence)")

        print(f"\n  Fundamental Score: {fund.total_score:.1f}/100")
        print(f"    Profitability : {fund.profitability_score:.0f}/25")
        print(f"    Fin. Health   : {fund.health_score:.0f}/20")
        print(f"    Valuation     : {fund.valuation_score:.0f}/25")
        print(f"    Growth        : {fund.growth_score:.0f}/20")
        print(f"    Dividends     : {fund.dividend_score:.0f}/10")

        print(f"\n  Technical: {tech.signal} (strength {tech.signal_strength:+d})")
        if tech.above_sma200:
            print("    ✅ Price above SMA200 — uptrend")
        if tech.rsi_weekly:
            print(f"    RSI {tech.rsi_weekly:.0f} | ADX {tech.adx:.0f}" if tech.adx else f"    RSI {tech.rsi_weekly:.0f}")

        if fund.graham_value:
            print(f"\n  Graham Value: ${fund.graham_value:.2f} | MoS: {fund.margin_of_safety_pct:.0f}%")

        if decision.rationale:
            print("\n  Rationale:")
            for r in decision.rationale:
                print(f"    ✅ {r}")
        if decision.risks:
            print("\n  Risks:")
            for r in decision.risks:
                print(f"    ⚠️  {r}")


def cmd_screen(n: int = 20) -> None:
    """Quick screen of the default universe."""
    tickers = DEFAULT_TICKERS[:n]
    results = []
    for sym in tickers:
        try:
            fund, tech, decision = full_analysis(sym)
            results.append((fund.total_score, sym, decision.action, tech.signal, fund.pe_ratio, fund.roe))
        except Exception as exc:
            logger.warning(f"{sym}: {exc}")

    results.sort(reverse=True)
    print(f"\n{'TICKER':<8} {'SCORE':>6} {'ACTION':<12} {'TECH':<10} {'PE':>6} {'ROE%':>6}")
    print("-" * 55)
    for score, sym, action, tech, pe, roe in results:
        pe_str = f"{pe:.1f}" if pe else "N/A"
        roe_str = f"{roe:.1f}" if roe else "N/A"
        print(f"{sym:<8} {score:>6.1f} {action:<12} {tech:<10} {pe_str:>6} {roe_str:>6}")


def cmd_portfolio() -> None:
    """Show current portfolio summary."""
    p = Portfolio()
    if not p.positions:
        print("No positions in portfolio.")
        return
    metrics = p.compute_metrics()
    print("\nPortfolio Summary")
    print(f"  Positions    : {metrics.num_positions}")
    print(f"  Total Value  : ${metrics.total_value:,.0f}")
    print(f"  Total P&L    : ${metrics.total_pnl:,.0f} ({metrics.total_pnl_pct:.1f}%)")
    print(f"  Ann. Return  : {metrics.annualized_return_pct:.1f}%")
    print(f"  Sharpe Ratio : {metrics.sharpe_ratio:.2f}")
    print(f"  Max Drawdown : {metrics.max_drawdown_pct:.1f}%")
    print(f"  Beta         : {metrics.beta:.2f}")


def cmd_dashboard() -> None:
    import subprocess
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])


def main():
    parser = argparse.ArgumentParser(
        description="Retirement Advisor — long-term investment analysis"
    )
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser("analyze", help="Full analysis for one or more tickers")
    p_analyze.add_argument("symbols", nargs="+", help="Ticker symbols (e.g. AAPL MSFT)")

    p_screen = sub.add_parser("screen", help="Quick-screen the default universe")
    p_screen.add_argument("--n", type=int, default=20, help="Max tickers to screen")

    sub.add_parser("portfolio", help="Show portfolio summary")
    sub.add_parser("dashboard", help="Launch Streamlit web dashboard")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze([s.upper() for s in args.symbols])
    elif args.command == "screen":
        cmd_screen(args.n)
    elif args.command == "portfolio":
        cmd_portfolio()
    elif args.command == "dashboard":
        cmd_dashboard()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
