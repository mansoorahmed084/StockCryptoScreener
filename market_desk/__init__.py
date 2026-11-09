"""Market Desk: a research + paper-trading desk, separate from the screener.

Night: backtest the rules (with fees) and read the news.
Morning: screen the watchlist and write trade plans for the rules that work.
All day: open and close paper trades when price hits the plan; price alerts.

Run ``python -m market_desk --help`` or ``streamlit run market_desk/app.py``.
Paper only: the desk never sends a real order.
"""
