import { useState, useEffect, useCallback } from "react";

// ─── PROGRESS STORAGE ───────────────────────────────────────
async function loadProgress() {
  try {
    const result = await window.storage.get("quant-progress");
    return result ? JSON.parse(result.value) : {};
  } catch {
    return {};
  }
}

async function saveProgress(progress) {
  try {
    await window.storage.set("quant-progress", JSON.stringify(progress));
  } catch (e) {
    console.error("Failed to save progress:", e);
  }
}

// ─── DATA ───────────────────────────────────────────────────
const PHASES = [
  {
    id: "bridge",
    title: "Bridge",
    subtitle: "From JoinQuant to Independent Analysis",
    color: "#b45309",
    weeks: "Week 1–2",
    description:
      "You learned JoinQuant's mechanics. Now you need to do the same things locally, on your own terms, with data you control. This phase gets your local environment working and rebuilds your confidence outside the platform.",
    gateCheck: null,
    projects: [
      {
        id: "p0",
        title: "Project 0: Local Data Pipeline",
        time: "3–5 sessions, ~1.5 hr each",
        goal: "Pull A-share data locally into pandas, clean it, and produce basic price/volume charts. By the end, you can do everything JoinQuant's 获取行情数据 did, but on your own machine.",
        builds: [
          "Fix data source access (baostock or AKShare fallback)",
          "pandas fundamentals: DataFrame, indexing, filtering, .loc/.iloc",
          "matplotlib basics: line plots, bar charts, subplots",
          "Save and load data locally as CSV (so you don't re-download every time)",
        ],
        newConcepts: [
          "OHLCV data structure and what each field means mechanically",
          "Stock code conventions: 6-digit codes, exchange suffixes (.SH/.SZ)",
          "前复权 vs 后复权 (forward vs backward adjustment) and why it matters",
        ],
        sessions: [
          {
            num: 1,
            title: "Environment setup + first data pull",
            tasks: [
              "Install Anaconda (or miniconda). Create a fresh conda environment: conda create -n quant python=3.11",
              "Install core packages: pip install baostock pandas matplotlib jupyter",
              "Open Jupyter, create a new notebook called data_pipeline.ipynb",
              "Write your first baostock query: pull daily 日K线 data for 平安银行 (sz.000001) for the last year",
              "Inspect the result: .head(), .shape, .dtypes, .info(). Notice that everything comes back as strings.",
              "Convert price columns to float, date to datetime. This is your first pandas cleaning task.",
            ],
            checkpoint:
              "You have a running Jupyter environment and can see a DataFrame with date, open, high, low, close, volume columns, all with correct dtypes.",
          },
          {
            num: 2,
            title: "pandas fundamentals: slicing, filtering, transforming",
            tasks: [
              "Practice .loc[] and .iloc[] — select rows by date range, select specific columns",
              "Filter: get only rows where volume > some threshold. Get only rows in a specific month.",
              "Set the date column as the index. Understand why time-series data uses DatetimeIndex.",
              "Try .resample('W').last() to convert daily data to weekly. Observe what happens to OHLCV.",
              "Compute a new column: daily price change = close - open. Add it to the DataFrame.",
              "Practice .sort_values(), .dropna(), .fillna() — you will use these constantly.",
            ],
            checkpoint:
              "You can filter a DataFrame to a date range, resample to weekly, and add computed columns without looking up syntax more than once or twice.",
          },
          {
            num: 3,
            title: "Visualization: price + volume charts",
            tasks: [
              "Plot a simple line chart of closing prices using plt.plot(). Add title, labels.",
              "Create a 2-row subplot: price on top, volume bars on bottom, sharing the x-axis.",
              "Add a 20-day moving average line to the price chart. Use .rolling(20).mean().",
              "Experiment with plt.style.use('seaborn-v0_8-whitegrid') or similar. Pick one you find readable.",
              "Plot two stocks on the same axes. Notice the scale problem. Try normalizing to starting price = 100.",
              "Save a figure to disk with plt.savefig(). You'll use this for deliverables.",
            ],
            checkpoint:
              "You can produce a clean price+volume chart with a moving average overlay for any stock, and it looks readable enough to show someone.",
          },
          {
            num: 4,
            title: "Build the reusable pipeline",
            tasks: [
              "Write a function get_stock_data(code, start, end) that handles baostock login/logout, queries, cleaning, and returns a clean DataFrame.",
              "Write a function plot_stock(df, title) that produces your standard price+volume chart.",
              "Add CSV caching: if a file for this stock+date range exists locally, load it instead of re-downloading.",
              "Create a /data folder. Store CSVs there. Test the cache by pulling the same stock twice.",
              "Pull data for 10 小盘股 from the 中证1000 index. Store them all. This is your working dataset.",
              "Write a simple loop that generates and saves charts for all 10 stocks.",
            ],
            checkpoint:
              "One function call pulls or loads data for any stock. One function call plots it. You have 10 stocks cached locally.",
          },
          {
            num: 5,
            title: "Polish + edge cases (optional but recommended)",
            tasks: [
              "Handle 停牌 (trading suspension): what does your data look like when a stock is halted? Add logic to detect gaps.",
              "Test with 前复权 (qfq) vs 不复权 (no adjustment). Plot both on the same chart for a stock that had a split. See the difference.",
              "Add error handling: what if baostock returns empty data? What if the stock code is wrong?",
              "Organize your notebook: add markdown headers, a table of contents cell, and a brief description of each function.",
              "Create a utils.py file with your functions. Import it into a clean notebook to verify it works standalone.",
            ],
            checkpoint:
              "Your pipeline handles edge cases gracefully, and someone else could read your notebook and understand what it does.",
          },
        ],
        pitfalls: [
          "baostock returns everything as strings — if you forget to convert, arithmetic silently fails or produces garbage. Always check .dtypes after loading.",
          "Using unadjusted prices (不复权) for analysis — splits and dividends create fake crashes in your charts. Default to 前复权 unless you have a specific reason not to.",
          "Hardcoding stock codes everywhere instead of using variables/functions — this makes it painful to switch stocks later. Parameterize from the start.",
          "Not caching data locally — baostock has rate limits and is slow. Download once, save to CSV, load from disk after that.",
          "Plotting without setting the date as the index — your x-axis will show integer positions instead of dates.",
        ],
        readyToMove: [
          "Can you pull daily OHLCV data for any A-share stock by code, without looking up the syntax?",
          "Can you explain what 前复权 does and why you need it for return calculations?",
          "Can you produce a price+volume chart with a moving average for any stock with one function call?",
          "Do you understand what each OHLCV field means and how volume relates to liquidity?",
        ],
        resources: [
          {
            title: "pandas 10 Minutes to pandas",
            note: "Official quick-start. Read the sections on selection, filtering, and operations.",
          },
          {
            title: "baostock 官方文档 (baostock.com)",
            note: "Reference for query parameters, especially 复权类型 and frequency options.",
          },
          {
            title: "matplotlib Pyplot tutorial",
            note: "Focus on subplots and the object-oriented interface (fig, ax = plt.subplots()). Skip the MATLAB-style plt.plot() shorthand.",
          },
        ],
        deliverable:
          "A Jupyter notebook that downloads daily data for 10 stocks, stores them locally, and plots price + volume for any stock with one function call.",
        connection:
          "This replaces JoinQuant's get_price(). You own the data now.",
      },
    ],
  },
  {
    id: "p1",
    title: "Phase 1",
    subtitle: "What Does the Data Actually Look Like?",
    color: "#1d4ed8",
    weeks: "Week 3–6",
    description:
      "Before you can test any trading idea, you need to understand the raw material: returns. This phase rebuilds your statistical intuition through direct observation of market data, focused specifically on 小盘股 vs 大盘股.",
    gateCheck: {
      title: "Before starting Phase 1",
      questions: [
        "Can you load data for any stock into a pandas DataFrame and filter it by date range?",
        "Do you have at least 10 stocks cached locally with clean OHLCV data?",
        "Can you produce a basic chart from a DataFrame without referencing documentation?",
      ],
      ifNo:
        "Go back to Project 0 sessions 2-4. The remaining projects all assume fluency with DataFrames and basic plotting.",
    },
    projects: [
      {
        id: "p1a",
        title: "Project 1: Return Distributions",
        time: "4–5 sessions",
        goal: "Compute daily returns for small-cap and large-cap baskets. Visualize their distributions. Discover that returns are NOT normally distributed, and understand why this matters for everything that comes later.",
        builds: [
          "Computing returns: simple vs log returns, and when each is appropriate",
          "pandas .pct_change(), .describe(), .rolling()",
          "Histograms, density plots, QQ-plots in matplotlib",
          "Basic descriptive stats: mean, median, std, skewness, kurtosis",
        ],
        newConcepts: [
          "What a return distribution is and what its shape tells you",
          "Fat tails: why extreme moves happen more often than a normal distribution predicts",
          "Volatility as standard deviation of returns (intuition before formula)",
          "Why 小盘股 have fatter tails: lower liquidity, information asymmetry, fewer institutional participants",
        ],
        sessions: [
          {
            num: 1,
            title: "Computing returns: the foundation of everything",
            tasks: [
              "Load one of your cached stocks. Compute simple returns: (P_today - P_yesterday) / P_yesterday. Do it manually first with a loop, then with .pct_change().",
              "Compute log returns: np.log(close / close.shift(1)). Compare to simple returns. They're nearly identical for small daily moves.",
              "When do they diverge? Compute both for a stock with a 涨停 (+10%) day. Notice the difference. Log returns are additive over time; simple returns are not.",
              "Plot simple returns as a time series. Notice the clusters of big moves. This is your first visual evidence of volatility clustering.",
              "Add a returns column to your DataFrame. Save it. You'll use returns, not prices, for almost everything going forward.",
            ],
            checkpoint:
              "You can compute both simple and log returns. You can explain when to use each: log returns for statistical analysis (additive over time), simple returns for portfolio P&L (multiplicative).",
          },
          {
            num: 2,
            title: "Descriptive statistics: summarizing the distribution",
            tasks: [
              "Use .describe() on your returns column. Understand each row: count, mean, std, min, 25%, 50%, 75%, max.",
              "Compute skewness with .skew(). Negative skew = more extreme down days than up days. Check: is your stock negatively skewed?",
              "Compute kurtosis with .kurtosis(). Positive excess kurtosis = fatter tails than normal. All stock return series have positive kurtosis. Verify this.",
              "Repeat for 3 small-cap and 3 large-cap stocks. Make a comparison table. Which group has higher kurtosis? Higher absolute skewness?",
              "Discuss with yourself (or write in a markdown cell): why would 小盘股 have fatter tails? Think about who trades these stocks and how information reaches them.",
            ],
            checkpoint:
              "You can compute mean, std, skew, kurtosis for any return series, and you can interpret what each number tells you about the shape of the distribution.",
          },
          {
            num: 3,
            title: "Visualizing distributions: histograms and density plots",
            tasks: [
              "Plot a histogram of daily returns for one stock. Try different bin counts (30, 50, 100). Notice how the shape changes.",
              "Overlay a normal distribution curve with the same mean and std. Use scipy.stats.norm.pdf(). Notice where the actual data deviates: the tails.",
              "Make a KDE (kernel density estimate) plot using df['returns'].plot.kde(). This is a smoothed histogram.",
              "Create a QQ-plot using scipy.stats.probplot(). Points on the diagonal = normal. Points curving away at the ends = fat tails. Your data will curve.",
              "Make a side-by-side comparison: one 小盘股 histogram vs one 大盘股 histogram. Same x-axis scale. The difference in tail behavior should be visible.",
            ],
            checkpoint:
              "You can produce a histogram with a normal overlay, a KDE plot, and a QQ-plot. You can point at the QQ-plot and explain what the tail deviation means.",
          },
          {
            num: 4,
            title: "Building the deliverable: 中证1000 vs 沪深300 comparison",
            tasks: [
              "Get constituent lists for 中证1000 and 沪深300. Baostock or AKShare may have index membership data; otherwise, download from 中证指数公司 website.",
              "Sample 20-30 stocks from each index (full constituents = slow). Pull daily data for 3 years.",
              "Compute daily returns for each stock. Then compute equal-weighted average daily returns for each basket.",
              "Produce the comparison: side-by-side histograms, summary statistics table, QQ-plots for both baskets.",
              "Write a conclusion in a markdown cell: what did you find? Are 小盘股 returns fatter-tailed? More volatile? More skewed?",
            ],
            checkpoint:
              "You have a complete notebook that someone could read from top to bottom and understand how 小盘股 and 大盘股 return distributions differ.",
          },
          {
            num: 5,
            title: "Formal normality testing (optional, extends your stats toolkit)",
            tasks: [
              "Run the Shapiro-Wilk test on your return series: scipy.stats.shapiro(). It will reject normality. Guaranteed.",
              "Run the Jarque-Bera test: scipy.stats.jarque_bera(). This specifically tests skewness and kurtosis vs normal.",
              "Discuss: if returns aren't normal, why does so much of finance assume they are? (Answer: mathematical convenience. The formulas are tractable. But the assumption breaks in the tails, which is exactly where risk management matters most.)",
              "Preview: in Phase 2, you'll learn hypothesis testing properly. This session gives you a taste of what 'testing an assumption about data' feels like.",
            ],
            checkpoint:
              "You can run a normality test and interpret the result. You understand that non-normality matters most for risk estimation and tail events.",
          },
        ],
        pitfalls: [
          "Computing returns on unadjusted prices — dividends and splits create fake return spikes. Always use 前复权 data.",
          "Ignoring 涨跌停 days in your distribution — a +10% or -10% return at the price limit is not the same as a freely-traded +10% move. The stock may have moved more if not capped. This truncates your measured tails.",
          "Looking at the histogram and concluding 'looks roughly normal' — the histogram hides tail behavior. Always check the QQ-plot. The tails are where the money and the risk live.",
          "Comparing distributions across different time periods without noting the regime — 2015 (crash) vs 2017 (calm) will give wildly different distributions for the same stock.",
        ],
        readyToMove: [
          "Can you compute and plot the return distribution for any stock or basket of stocks?",
          "Can you explain, in your own words, what fat tails mean for a trader? (Hint: extreme days happen more than you'd expect.)",
          "Can you interpret a QQ-plot — what does deviation at the tails tell you?",
          "Do you understand why mean and standard deviation alone are insufficient to describe returns?",
        ],
        resources: [
          {
            title: "scipy.stats documentation",
            note: "Reference for norm.pdf, probplot (QQ-plots), shapiro, jarque_bera. Bookmark this; you'll use scipy.stats throughout.",
          },
          {
            title: "Mandelbrot, The (Mis)Behavior of Markets, Ch. 1-3",
            note: "Optional but eye-opening. Mandelbrot's case that markets are wilder than finance theory admits. Readable without advanced math.",
          },
        ],
        deliverable:
          "A notebook comparing return distributions of 中证1000 constituents vs 沪深300 constituents, with histograms and summary statistics side by side.",
        connection:
          "Every strategy you'll ever test makes assumptions about how returns behave. This project forces you to see the actual data instead of assuming.",
      },
      {
        id: "p1b",
        title: "Project 2: Volatility & Risk",
        time: "4–5 sessions",
        goal: "Build a volatility analysis toolkit. Understand what risk looks like in the data, not just as a number on JoinQuant's backtest report.",
        builds: [
          "Rolling window calculations (rolling mean, rolling std)",
          "Drawdown calculation and visualization",
          "Sharpe ratio: what it actually measures and what it hides",
          "Annualization: converting daily stats to yearly (and the √252 rule)",
        ],
        newConcepts: [
          "Volatility clustering: why big moves follow big moves",
          "Maximum drawdown: the metric that kills strategies (and traders)",
          "Risk-adjusted returns: why raw returns are misleading",
          "涨跌停板 (price limits) and how they distort measured volatility in A-shares",
        ],
        sessions: [
          {
            num: 1,
            title: "Rolling calculations: seeing volatility change over time",
            tasks: [
              "Compute 20-day rolling mean of returns. Plot it. This is a smoothed view of recent average daily return.",
              "Compute 20-day rolling standard deviation of returns. Plot it. This IS rolling volatility. When it spikes, the stock is moving more.",
              "Plot rolling volatility for a 小盘股 and a 大盘股 on the same axes. Notice the difference in baseline level AND in spike magnitude.",
              "Try different windows (10, 20, 60 days). Shorter windows = noisier but more responsive. Longer = smoother but slower to react. There's no single right answer.",
              "Identify a period of volatility clustering in your data: a stretch where high-vol days bunch together. Mark it on the chart with axvspan().",
            ],
            checkpoint:
              "You can compute and plot rolling volatility. You can identify volatility clustering visually and explain the mechanism: uncertainty begets uncertainty, and market participants react to recent volatility by adjusting their own behavior.",
          },
          {
            num: 2,
            title: "Drawdown: the metric that actually kills you",
            tasks: [
              "Compute cumulative returns: (1 + returns).cumprod(). This is your equity curve assuming you started with 1 unit.",
              "Compute the running maximum of the equity curve: cummax().",
              "Drawdown = (equity_curve - running_max) / running_max. Plot it as a filled area chart (always negative or zero).",
              "Find the maximum drawdown: .min() of the drawdown series. Find WHEN it happened: .idxmin().",
              "Compute the duration of the worst drawdown: how many days from peak to trough? How many from trough to recovery?",
              "Compare max drawdown for a 小盘股 basket vs 大盘股 basket. Which is worse? Is the answer always the same across time periods?",
            ],
            checkpoint:
              "You can compute and plot a drawdown curve, identify the max drawdown, and explain why drawdown is arguably more important than total return for evaluating a strategy.",
          },
          {
            num: 3,
            title: "Sharpe ratio: what it measures and what it hides",
            tasks: [
              "Compute the daily Sharpe ratio: mean(returns) / std(returns). This is the reward-to-risk ratio.",
              "Annualize it: multiply by √252 (there are ~252 trading days per year). Understand why: mean scales linearly with time, std scales with √time.",
              "Include the risk-free rate: Sharpe = (mean_return - rf) / std. Use the 1-year 国债 yield (around 1.5-2%) divided by 252 for daily rf.",
              "Compute Sharpe for your 小盘股 and 大盘股 baskets. Higher return doesn't always mean higher Sharpe. Check which basket has the better risk-adjusted return.",
              "The Sharpe ratio's hidden assumption: it treats upside and downside volatility equally. A stock that often jumps UP has high std but that's good for you. The Sortino ratio fixes this: compute it using only downside std.",
              "Compute Sharpe over rolling 1-year windows. Notice how unstable it is. A strategy with a Sharpe of 2.0 in-sample can easily be 0.5 out-of-sample.",
            ],
            checkpoint:
              "You can compute and annualize the Sharpe ratio, and you can explain at least two ways it misleads: (1) symmetric treatment of up/down volatility, (2) instability over different time windows.",
          },
          {
            num: 4,
            title: "涨跌停板 effects + A-share specific risk features",
            tasks: [
              "Identify all days in your data where a stock hit ±10% (or ±20% for 创业板/科创板). Count them. Plot them on the price chart.",
              "On 涨停/跌停 days, the measured return is capped. The stock might have moved more if the limit didn't exist. This means your measured volatility UNDERSTATES true volatility for limit-hit stocks.",
              "Check: do 小盘股 hit limits more often than 大盘股? Count limit-hit days as a percentage for each basket.",
              "Investigate a 连续跌停 (consecutive limit-down) episode. Pull data for a stock that had multiple consecutive limit-down days. Plot it. This is the liquidity risk that doesn't show up in simple volatility measures: you can't sell.",
              "Write a markdown cell: what does this mean for your strategy? If you hold a 小盘股 that hits 跌停, you're locked in. Your measured risk underestimates your actual risk.",
            ],
            checkpoint:
              "You can identify 涨跌停 days in data, quantify their frequency, and explain how price limits distort volatility measurement and create liquidity traps.",
          },
          {
            num: 5,
            title: "Build the risk toolkit module (optional but high-value)",
            tasks: [
              "Create a file: risk_toolkit.py with functions: compute_rolling_vol(), compute_drawdown(), compute_sharpe(), compute_sortino(), compute_max_dd().",
              "Each function takes a returns Series and relevant parameters, returns the computed metric.",
              "Write a summary function: risk_report(returns) that prints/returns a dict with all key metrics.",
              "Test it on your 10 stocks. Generate a risk comparison table.",
              "Import risk_toolkit into a fresh notebook to verify it works standalone. You'll reuse this in every future project.",
            ],
            checkpoint:
              "You have a reusable risk_toolkit.py that you can import and use in one line. You've tested it on multiple stocks.",
          },
        ],
        pitfalls: [
          "Using calendar days instead of trading days for annualization — China has ~242-244 trading days per year (holidays differ from US). Using 252 (US convention) introduces a small error. Not fatal, but good to know.",
          "Comparing Sharpe ratios across different time periods — a Sharpe computed during a bull market is meaningless for predicting performance in a bear market. Always note the time period.",
          "Ignoring drawdown duration — a 30% drawdown that recovers in 2 months is very different from a 30% drawdown that takes 2 years to recover. Duration matters for real money management.",
          "Treating max drawdown as the worst that can happen — max drawdown is the worst IN YOUR DATA. The future can always be worse. This is survivorship bias applied to risk metrics.",
        ],
        readyToMove: [
          "Can you compute rolling volatility, drawdown, and Sharpe ratio from scratch without referencing code?",
          "Can you explain why max drawdown matters more than average return for a real trader?",
          "Can you describe how 涨跌停板 distorts volatility measurement and creates hidden risk?",
          "Do you have a reusable risk toolkit (even a rough one) that you can apply to new data?",
        ],
        resources: [
          {
            title: "AQR: Understanding Drawdowns (paper)",
            note: "Practitioner-level paper on drawdown analysis. Focus on the intuition sections, skip the heavy math.",
          },
          {
            title: "Your own Phase 1 code from Project 1",
            note: "You'll reuse the returns computation and distribution tools you already built. If they're messy, clean them up now.",
          },
        ],
        deliverable:
          "A notebook that calculates rolling volatility, drawdown curves, and Sharpe ratios for your stock baskets. You'll reuse these functions in every future project.",
        connection:
          "JoinQuant showed you 最大回撤 and 夏普比率 as output numbers. Now you understand what drives those numbers and when they mislead you.",
      },
    ],
  },
  {
    id: "p2",
    title: "Phase 2",
    subtitle: "Is This Pattern Real or Just Noise?",
    color: "#6d28d9",
    weeks: "Week 7–10",
    description:
      "You've seen patterns in the data. The critical question is whether they're real (persistent, exploitable) or just random noise that happened to look meaningful. This phase gives you the statistical tools to tell the difference.",
    gateCheck: {
      title: "Before starting Phase 2",
      questions: [
        "Can you compute returns, rolling volatility, drawdown, and Sharpe for any stock or basket?",
        "Can you explain what fat tails are and why they matter for risk?",
        "Do you have working, reusable code from Phase 1 that you can build on?",
      ],
      ifNo:
        "Finish the Phase 1 deliverables. Phase 2 tools operate on the returns data and risk metrics you built in Phase 1.",
    },
    projects: [
      {
        id: "p2a",
        title: "Project 3: Correlation & Regression",
        time: "4–5 sessions",
        goal: "Learn to measure relationships between variables. Does volume predict returns? Does yesterday's return predict today's? Build the tools to answer these questions rigorously instead of by eyeballing charts.",
        builds: [
          "Correlation: Pearson vs Spearman (rank), and when each is appropriate",
          "Scatter plots with trend lines",
          "Simple linear regression with scipy or statsmodels",
          "Reading regression output: R², p-value, coefficients",
        ],
        newConcepts: [
          "Correlation ≠ causation (with concrete market examples)",
          "Autocorrelation: does a stock's past predict its future?",
          "Why autocorrelation is low in large-caps but sometimes detectable in small-caps (mechanism: slower information diffusion, fewer algo traders arbing it away)",
          "Spurious correlation and data-mining bias",
        ],
        sessions: [
          {
            num: 1,
            title: "Correlation: measuring relationships between variables",
            tasks: [
              "Load returns for two stocks. Compute Pearson correlation using .corr(). Interpret: +1 = move together, 0 = no relationship, -1 = opposite.",
              "Make a scatter plot: stock A returns on x-axis, stock B returns on y-axis. Each dot = one day. Does the cloud tilt?",
              "Compute a correlation matrix for your 10-stock basket. Visualize with seaborn.heatmap() (pip install seaborn). Look for clusters.",
              "Learn when Pearson fails: it measures LINEAR relationships only. If the relationship is nonlinear or there are outliers, Spearman (rank) correlation is more robust. Compute both and compare.",
              "Compute correlation between returns and volume changes. Is there a relationship? Think about what mechanism would cause one.",
            ],
            checkpoint:
              "You can compute and interpret Pearson and Spearman correlation, produce a correlation heatmap, and explain when Pearson is misleading.",
          },
          {
            num: 2,
            title: "Scatter plots with trend lines + residual thinking",
            tasks: [
              "For two correlated stocks, make a scatter plot and add a best-fit line using np.polyfit(x, y, 1).",
              "Add the equation and R² value to the plot. R² = fraction of variance in Y explained by X. Low R² + significant slope = real relationship but noisy.",
              "Plot the residuals (actual - predicted). They should look random. If they show a pattern, the linear model misses something.",
              "Try a clearly unrelated pair (e.g., a bank stock vs a tech stock). Show that the correlation is low and the scatter plot is a blob.",
              "Key insight to internalize: even a 'significant' correlation of 0.1 means only 1% of variance explained. In markets, small correlations can be real and usable, but they're also fragile.",
            ],
            checkpoint:
              "You can add a regression line to a scatter plot, compute R², and interpret whether a relationship is strong enough to care about.",
          },
          {
            num: 3,
            title: "Simple linear regression with statsmodels",
            tasks: [
              "pip install statsmodels. Run a simple OLS: does yesterday's return predict today's return?",
              "Read the output: coefficient (slope), p-value, R², confidence intervals. Focus on the p-value: is the relationship statistically distinguishable from zero?",
              "Run the same regression for a 大盘股 and a 小盘股. Compare the coefficients and p-values. Autocorrelation should be weaker in large-caps.",
              "Try a different predictor: does yesterday's volume change predict today's return? Run the regression.",
              "Important: a low p-value does not mean a tradable signal. Statistical significance ≠ economic significance. A coefficient of 0.001 might be 'significant' with enough data but worthless after transaction costs.",
            ],
            checkpoint:
              "You can run a linear regression, read the output summary, and explain the difference between statistical significance and practical usefulness.",
          },
          {
            num: 4,
            title: "Autocorrelation: does the past predict the future?",
            tasks: [
              "Compute lag-1 autocorrelation of returns: df['returns'].autocorr(lag=1). This is the correlation of a stock with its own past.",
              "Compute autocorrelation for lags 1 through 20. Plot the autocorrelation function (ACF). Use statsmodels.graphics.tsaplots.plot_acf().",
              "Compare ACF plots for 小盘股 vs 大盘股. The mechanism: in small-caps, information diffuses slowly (fewer analysts, less institutional attention, less algo trading). This can create short-term predictability.",
              "But: autocorrelation in returns is typically very small (0.01-0.05 range). Is yours statistically different from zero? The ACF plot shows confidence bands; any bar outside the bands is 'significant.'",
              "This is your first real hypothesis test in disguise: H₀ = autocorrelation is zero. The ACF confidence bands are the test.",
            ],
            checkpoint:
              "You can compute and plot the autocorrelation function, identify significant lags, and explain the economic mechanism that produces autocorrelation in small-caps.",
          },
          {
            num: 5,
            title: "Spurious correlation + data-mining awareness (optional but critical)",
            tasks: [
              "Generate a random return series: np.random.normal(0, 0.02, 1000). Compute its correlation with your real stock. It should be near zero... but run it 100 times. Some runs will show 'significant' correlation by chance.",
              "This is the core problem of data mining: if you test enough relationships, you will find patterns that are pure noise. Keep a count of how many of 100 random series show |corr| > 0.05.",
              "Google 'spurious correlations' (Tyler Vigen). Divorce rate in Maine correlates with margarine consumption. The data is real; the relationship is not.",
              "Write a reflection: how does this apply to factor research? If you test 100 factors, roughly 5 will appear 'significant' at p < 0.05 by pure chance. This is the multiple testing problem, which you'll formalize in Project 4.",
            ],
            checkpoint:
              "You understand viscerally (not just theoretically) that random data produces patterns, and that testing many hypotheses guarantees false positives.",
          },
        ],
        pitfalls: [
          "Confusing correlation with causation — volume and returns may correlate because a third factor drives both (e.g., news events), not because volume 'causes' returns.",
          "Using Pearson correlation on data with outliers — one extreme day can dominate the correlation. Use Spearman or winsorize outliers first.",
          "Celebrating small autocorrelations without checking transaction costs — an autocorrelation of 0.02 generates a tiny expected return per trade, easily eaten by commissions and slippage.",
          "Testing many lags and only reporting the significant one — this is the multiple testing problem. If you test 20 lags, one will be 'significant' by chance.",
        ],
        readyToMove: [
          "Can you compute and interpret Pearson, Spearman, and autocorrelation?",
          "Can you run a regression and explain what the coefficient, p-value, and R² tell you?",
          "Can you explain why testing many hypotheses inflates false positives?",
          "Do you have a testable finding (e.g., autocorrelation in 小盘股) ready for proper significance testing?",
        ],
        resources: [
          {
            title: "statsmodels OLS documentation",
            note: "Reference for regression. Focus on the summary() output interpretation.",
          },
          {
            title: "Tyler Vigen, Spurious Correlations (tylervigen.com)",
            note: "Fun and sobering. Look at these before you get excited about any correlation you find in market data.",
          },
        ],
        deliverable:
          "A notebook that tests whether 小盘股 returns show statistically significant autocorrelation, and whether volume changes predict next-day returns.",
        connection:
          "This is your first real hypothesis test. You're moving from 'looking at data' to 'testing claims about data.' Every factor you'll evaluate later uses these same tools.",
      },
      {
        id: "p2b",
        title: "Project 4: Hypothesis Testing",
        time: "3–4 sessions",
        goal: "Formalize 'is this real?' into a rigorous framework. Learn to quantify the probability that a pattern you see is just luck.",
        builds: [
          "Null hypothesis and p-values (intuition first, then mechanics)",
          "t-tests: comparing two groups of returns",
          "Multiple testing problem: why testing 100 factors guarantees false positives",
          "Bootstrap methods as an alternative when distributions aren't normal",
        ],
        newConcepts: [
          "Statistical significance vs economic significance (a real return of 0.01% can be 'significant' but worthless)",
          "Why most published trading strategies don't work: publication bias + overfitting",
          "The Bonferroni correction and why quants care about it",
        ],
        sessions: [
          {
            num: 1,
            title: "Null hypothesis and p-values: the intuition",
            tasks: [
              "Start with an analogy: you flip a coin 100 times and get 60 heads. Is the coin unfair? The null hypothesis says 'the coin is fair (p=0.5).' The p-value asks: if the coin were fair, how likely is 60+ heads?",
              "Simulate this in Python: flip 100 coins 10,000 times (np.random.binomial). Count how often you get 60+. That fraction is your p-value.",
              "Now translate to markets: your null hypothesis is 'this factor has zero predictive power' (returns after high-factor days = returns after low-factor days). The p-value asks: if the factor were useless, how likely is the pattern I observed?",
              "A p-value of 0.03 does NOT mean there's a 3% chance the null is true. It means: IF the null were true, there's a 3% chance of data this extreme. This distinction trips up even professionals.",
              "Apply to your autocorrelation finding from Project 3: what's the null? What's the p-value? Is it below 0.05?",
            ],
            checkpoint:
              "You can explain what a p-value measures (and doesn't measure), set up a null hypothesis for a market claim, and compute a p-value via simulation.",
          },
          {
            num: 2,
            title: "t-tests: comparing two groups rigorously",
            tasks: [
              "Split your 小盘股 returns into two groups: days after positive returns vs days after negative returns. Is the mean return different between the groups?",
              "Run a two-sample t-test: scipy.stats.ttest_ind(). Read the t-statistic and p-value.",
              "Do the same for your 大盘股 basket. Compare the p-values. Is the pattern stronger in small-caps?",
              "Try a paired t-test: for each day, compute the return difference (小盘 - 大盘). Test whether this difference is significantly different from zero. This tests whether small-caps consistently outperform.",
              "Inspect the effect size, not just the p-value. A mean daily return difference of 0.002% might be significant with 5 years of data, but it's economically meaningless. Always compute: 'how many basis points per day is this?' and 'does it cover transaction costs?'",
            ],
            checkpoint:
              "You can set up and run a t-test, interpret the result, and critically assess whether a statistically significant result is economically meaningful.",
          },
          {
            num: 3,
            title: "Multiple testing and the Bonferroni correction",
            tasks: [
              "Simulation exercise: generate 100 random (zero-mean) return series. For each, test whether the mean is different from zero. Count how many have p < 0.05. You should get roughly 5. These are false positives.",
              "This is the multiple testing problem. At α = 0.05, testing 100 hypotheses produces ~5 false positives by construction. If you tested 100 factors and found 5 'significant' ones, you might have found nothing real.",
              "The Bonferroni correction: divide your threshold by the number of tests. If you test 100 factors, require p < 0.05/100 = 0.0005 for significance. Harsh, but it controls the false positive rate.",
              "Apply this to your work: if you tested autocorrelation at 20 different lags, your effective threshold should be 0.05/20 = 0.0025. Do your significant lags survive?",
              "Discuss: this is why most published strategies fail. Researchers test hundreds of ideas and publish the ones that 'work.' The publication filter is a multiple testing problem. This is called p-hacking.",
            ],
            checkpoint:
              "You can explain the multiple testing problem, apply the Bonferroni correction, and evaluate whether a finding survives adjustment.",
          },
          {
            num: 4,
            title: "Bootstrap methods: when you can't assume normality (optional but powerful)",
            tasks: [
              "The t-test assumes returns are roughly normal. You proved in Project 1 they're not. Bootstrap doesn't need this assumption.",
              "Implement a bootstrap test: resample your returns WITH replacement 10,000 times. Compute the mean for each resample. This gives you a distribution of possible means.",
              "The 95% confidence interval is the 2.5th and 97.5th percentile of bootstrap means. If zero is outside this interval, the mean is 'significantly' different from zero.",
              "Compare bootstrap and t-test results for the same data. They'll usually agree for large samples, but diverge when tails are extreme (exactly the 小盘股 case).",
              "Build a reusable function: bootstrap_test(data, n_iterations=10000, ci=0.95). You'll use this in Phase 3.",
            ],
            checkpoint:
              "You can run a bootstrap hypothesis test and explain when and why it's preferable to a t-test (non-normal distributions, small samples, fat tails).",
          },
        ],
        pitfalls: [
          "Treating p < 0.05 as proof — it's a convention, not a law of nature. In trading, where the stakes are financial, you should probably require stronger evidence (p < 0.01 or better).",
          "Ignoring multiple testing — every factor you test, every parameter you tune, every time period you select is an implicit hypothesis test. The more you test, the more likely you are to find something that looks real but isn't.",
          "Forgetting economic significance — always convert your statistical finding to a dollar amount. 'Significant autocorrelation' means nothing if the expected return per trade is smaller than your commission.",
          "Applying parametric tests to non-parametric data — stock returns have fat tails. Bootstrap methods are more honest about uncertainty.",
        ],
        readyToMove: [
          "Can you explain the null hypothesis framework and what p-values measure?",
          "Can you run and interpret a t-test and a bootstrap test?",
          "Can you apply the Bonferroni correction to adjust for multiple testing?",
          "Given a 'significant' finding, can you assess whether it's economically meaningful after transaction costs?",
        ],
        resources: [
          {
            title: "Harvey, Liu, and Zhu: '...and the Cross-Section of Expected Returns' (2016)",
            note: "Landmark paper arguing that most published cross-sectional return predictors are false discoveries. Read the introduction and conclusion. The core argument: factor research suffers from massive multiple testing.",
          },
          {
            title: "Your Project 3 autocorrelation results",
            note: "This project takes your Project 3 findings and puts them through rigorous testing. Have your Project 3 notebook open.",
          },
        ],
        deliverable:
          "A notebook that takes your autocorrelation finding from Project 3 and runs proper significance tests. Is the pattern strong enough to trade on, or just noise?",
        connection:
          "This is the single most important skill in quant trading. The ability to distinguish signal from noise is what separates profitable quants from people who overfit backtests.",
      },
    ],
  },
  {
    id: "p3",
    title: "Phase 3",
    subtitle: "What Is a Factor and How Do I Find One?",
    color: "#047857",
    weeks: "Week 11–16",
    description:
      "This is the phase that answers your core question: 'how do I identify relevant factors and write them into code?' A factor is a measurable characteristic of a stock that predicts future returns. This phase teaches you to think in factors, test them, and combine them.",
    gateCheck: {
      title: "Before starting Phase 3",
      questions: [
        "Can you run a hypothesis test and interpret the p-value correctly?",
        "Can you explain the multiple testing problem and apply a correction?",
        "Can you distinguish between statistical significance and economic significance?",
        "Do you have working correlation, regression, and bootstrap tools from Phase 2?",
      ],
      ifNo:
        "Phase 3 applies every statistical tool from Phase 2 to factor evaluation. If your testing tools are shaky, your factor evaluations will be unreliable.",
    },
    projects: [
      {
        id: "p3a",
        title: "Project 5: Your First Factor — Size",
        time: "5–6 sessions",
        goal: "Implement the size factor (市值因子) from scratch. This is the most intuitive factor for your 小盘股 thesis: do smaller stocks earn higher returns? Test it rigorously.",
        builds: [
          "Getting 市值 (market cap) data programmatically",
          "Quintile sorting: split stocks into 5 groups by size, compare returns",
          "IC (Information Coefficient): measuring how well a factor predicts returns",
          "Turnover analysis: how often does a factor's ranking change?",
        ],
        newConcepts: [
          "What a factor model IS (a structured bet that one measurable thing predicts returns)",
          "The Fama-French size premium: history, mechanism, and the debate about whether it still exists",
          "Why small-cap outperformance may be compensation for risk (illiquidity, bankruptcy) rather than a free lunch",
          "Survivorship bias in small-cap studies: dead companies vanish from the data",
        ],
        sessions: [
          {
            num: 1,
            title: "Getting 市值 data and understanding what market cap measures",
            tasks: [
              "Market cap = share price × shares outstanding. It measures total value of a company's equity. 小盘股 typically means market cap below some threshold (varies by definition: 中证1000 uses a specific ranking cutoff).",
              "Pull 市值 data from your data source. Baostock: use query_stock_basic or query_profit_data. AKShare: stock_zh_a_spot_em() gives real-time data with 总市值 column.",
              "For historical factor testing, you need market cap AT EACH POINT IN TIME, not today's market cap. This is critical. Using today's market cap to sort historical stocks is look-ahead bias.",
              "Create a DataFrame: rows = dates, columns = stock codes, values = market cap. This is a 'factor matrix.' Fill NaN for dates where a stock wasn't listed or was suspended.",
              "Inspect the distribution of market caps: plot a histogram. It's heavily right-skewed (few giant companies, many small ones). Apply log transform: np.log(market_cap). Now it's closer to normal.",
            ],
            checkpoint:
              "You have a time-series of market cap data for a universe of stocks, with no look-ahead bias in the data construction.",
          },
          {
            num: 2,
            title: "Quintile sorting: the standard factor test methodology",
            tasks: [
              "For each month (or rebalancing date), rank all stocks by market cap. Split into 5 equal groups (quintiles): Q1 = smallest, Q5 = largest.",
              "Compute equal-weighted returns for each quintile over the following month. This is the return you would have earned by holding that quintile.",
              "Repeat across all months in your sample. You now have 5 return series, one per quintile.",
              "Plot cumulative returns for all 5 quintiles on the same chart. Does Q1 (smallest) outperform Q5 (largest)? By how much?",
              "Compute the 'long-short return': Q1 return minus Q5 return for each month. This isolates the size factor. Plot its cumulative return. Is it consistently positive, or does it go through long losing streaks?",
            ],
            checkpoint:
              "You can sort stocks into quintiles by any characteristic, track quintile returns, and compute a long-short factor return.",
          },
          {
            num: 3,
            title: "IC (Information Coefficient): a more granular test",
            tasks: [
              "IC = rank correlation between factor value at time t and stock returns at time t+1. Use Spearman (rank) correlation because you care about ordinal relationship, not linear.",
              "For each month: rank stocks by market cap, rank stocks by next-month return, compute Spearman correlation. This is one month's IC.",
              "Compute IC for every month. You now have a time series of IC values. The mean IC (ICIR when adjusted for volatility) tells you average predictive power.",
              "Interpretation: IC of 0.05 is considered decent for a single factor. IC of 0.10 is strong. IC of 0.20 is extraordinary (and suspicious).",
              "Plot IC over time. Is it stable? Does it flip negative in some periods? A factor that works in bull markets but reverses in bear markets is less useful than one that's consistently positive (even if small).",
            ],
            checkpoint:
              "You can compute and interpret IC for any factor, distinguish between stable and unstable factors, and explain why IC is preferable to simple quintile returns for factor evaluation.",
          },
          {
            num: 4,
            title: "Survivorship bias: the hidden trap in small-cap research",
            tasks: [
              "Your stock universe probably only includes stocks that exist TODAY. But some stocks that existed 5 years ago have since been delisted (退市). These tend to be small-caps that went bankrupt.",
              "This is survivorship bias: by excluding dead companies, you overstate the returns of the small-cap quintile. The companies that failed would have dragged Q1 returns down.",
              "Check: how many stocks in your universe were listed throughout the entire sample period vs. how many appeared or disappeared? Use your data source to get listing/delisting dates.",
              "If possible, include delisted stocks in your backtest. If your data source doesn't have them, acknowledge the bias explicitly and estimate its magnitude: 'if N stocks were delisted and each lost 100%, the Q1 return would be adjusted by approximately X%.'",
              "Write a markdown cell explaining how survivorship bias affects your size factor results, and in which direction (it overstates small-cap returns).",
            ],
            checkpoint:
              "You can identify survivorship bias in your dataset, estimate its approximate impact, and explain why small-cap studies are especially vulnerable to it.",
          },
          {
            num: 5,
            title: "Fama-French size premium: context and debate",
            tasks: [
              "Background reading: the Fama-French three-factor model (1993) documented that small stocks outperform large stocks historically. This is the 'size premium' or SMB (Small Minus Big) factor.",
              "The mechanism (risk-based): small-caps are riskier (illiquid, more likely to fail, less diversified businesses). The premium compensates investors for bearing this risk. It's not a free lunch; it's an insurance premium.",
              "The mechanism (behavioral): small-caps get less attention from analysts and institutions. Information reaches them slower. This creates temporary mispricings that can be exploited.",
              "The debate: the size premium has been weak or absent in many markets since publication. Possible explanations: (1) it was arbed away, (2) it was always a statistical artifact, (3) it's conditional on other factors (e.g., only works in value stocks).",
              "Where A-shares stand: the Chinese small-cap premium has been historically stronger than in the US, partly due to greater retail participation and speculative activity. But post-2017 regulatory changes and the rise of quant funds may have reduced it. Check your own data.",
            ],
            checkpoint:
              "You can explain the Fama-French size premium, articulate both the risk-based and behavioral mechanisms, and assess whether the premium exists in your A-share data sample.",
          },
          {
            num: 6,
            title: "Turnover analysis + putting it all together (optional)",
            tasks: [
              "Turnover = what fraction of stocks change quintiles each rebalancing period. High turnover = expensive to trade (more commissions, more slippage).",
              "Compute monthly turnover for your size factor. Market cap is relatively stable, so turnover should be low. Compare to momentum (which you'll build in Project 6): turnover will be much higher.",
              "Estimate transaction cost impact: if turnover is T%, and each trade costs C% in slippage + commission, the drag is T × C per rebalance.",
              "Write the full Project 5 report: factor definition, quintile chart, IC time series, survivorship bias assessment, turnover, estimated transaction cost drag, and your conclusion: is the size factor usable in A-shares?",
            ],
            checkpoint:
              "You have a complete, honest evaluation of the size factor in A-shares, including strengths, weaknesses, and cost considerations.",
          },
        ],
        pitfalls: [
          "Using today's market cap to sort historical stocks — this is look-ahead bias. The biggest mistake in factor research. You MUST use the market cap known at each point in time.",
          "Ignoring survivorship bias — your Q1 (smallest) quintile is missing all the tiny stocks that went bankrupt. This inflates apparent small-cap returns.",
          "Rebalancing too often without accounting for costs — monthly rebalancing may look good in a backtest with zero transaction costs. Add costs and the picture changes.",
          "Comparing your IC to published numbers without matching methodology — different universes, different time periods, different IC calculation methods give different numbers.",
        ],
        readyToMove: [
          "Can you implement quintile sorting and IC calculation from scratch for any factor?",
          "Can you explain survivorship bias and how it specifically affects small-cap factor research?",
          "Can you articulate the economic mechanism behind the size premium (both risk-based and behavioral)?",
          "Do you have a reusable factor testing framework that you can apply to new factors?",
        ],
        resources: [
          {
            title: "Fama & French: 'Common Risk Factors in the Returns on Stocks and Bonds' (1993)",
            note: "The original paper. Read the introduction and the discussion of SMB. Skip the bond factors for now.",
          },
          {
            title: "Asness et al.: 'Size Matters, If You Control Your Junk' (2018)",
            note: "Shows that the size premium revives when you exclude low-quality small-caps. Relevant to your factor combination work in Project 6.",
          },
        ],
        deliverable:
          "A notebook that sorts A-share stocks into quintiles by market cap, tracks each quintile's returns over 3+ years, and computes the size factor's IC.",
        connection:
          "This is the direct, testable version of your 小盘股 thesis. Instead of 'small-caps have opportunities,' you now have a number: the size factor's IC, its stability, and its drawdowns.",
      },
      {
        id: "p3b",
        title: "Project 6: Multi-Factor Analysis",
        time: "5–6 sessions",
        goal: "Test additional factors (value, momentum, volatility) and learn how factors interact. Build a factor scoring system.",
        builds: [
          "Value factor: P/E, P/B ratios from financial data",
          "Momentum factor: past N-day returns as a predictor",
          "Combining factors: z-score normalization and composite scoring",
          "Factor correlation matrix: are your factors telling you the same thing?",
        ],
        newConcepts: [
          "Why factors work: behavioral explanations (anchoring, herding, overreaction) vs risk-based explanations",
          "Factor crowding: when too many people trade the same factor, it stops working",
          "Momentum crashes: the specific failure mode of momentum strategies in small-caps",
          "Value traps: when cheap stocks are cheap for a reason",
        ],
        sessions: [
          {
            num: 1,
            title: "Value factor: P/E and P/B",
            tasks: [
              "Pull fundamental data: P/E (市盈率) and P/B (市净率). AKShare or baostock quarterly financials. Again, use POINT-IN-TIME data, not current values.",
              "Negative P/E (loss-making companies) requires special handling: exclude them or use the inverse (E/P) which handles negatives more naturally.",
              "Run the quintile sort on P/B: Q1 = lowest P/B (cheapest), Q5 = highest (most expensive). Track returns. Do cheap stocks outperform?",
              "Compute IC for the value factor the same way you did for size.",
              "The mechanism: value works because investors overreact to bad news, pushing prices too low for out-of-favor stocks. Also, cheap stocks may carry genuine risk (financial distress, bad management).",
            ],
            checkpoint:
              "You have a working value factor with quintile returns and IC. You can explain the mechanism and the risk: some cheap stocks are cheap because they're dying (value traps).",
          },
          {
            num: 2,
            title: "Momentum factor: past returns as predictor",
            tasks: [
              "Compute trailing N-day returns (e.g., past 60 trading days, skipping the most recent 5 days — the skip avoids short-term reversal effects).",
              "Run the quintile sort: Q1 = worst recent performers, Q5 = best. Track forward returns. Does Q5 outperform Q1?",
              "Compute IC for momentum. Compare its magnitude and stability to your size and value ICs.",
              "The mechanism: momentum works because information diffuses slowly (especially in 小盘股) and because investors herd (buying winners, selling losers creates self-reinforcing trends). It stops working when the trend reverses suddenly.",
              "Momentum crashes: in 2008-2009 and during China's 2015 crash, momentum factors suffered massive losses. Past winners became the biggest losers. This is the specific tail risk of momentum strategies.",
            ],
            checkpoint:
              "You have a working momentum factor. You can explain the information diffusion mechanism and the momentum crash failure mode.",
          },
          {
            num: 3,
            title: "Factor correlations: are your factors redundant?",
            tasks: [
              "For each stock at each date, you now have 3 factor scores: size, value, momentum. Compute the cross-sectional correlation between each pair at each date.",
              "Average the correlations over time. Size and value are often negatively correlated (small stocks tend to have lower P/B). If corr is high, the factors are partially redundant.",
              "Plot how factor correlations change over time. Stable correlations = predictable. Unstable = harder to combine reliably.",
              "The goal: you want factors with LOW correlation to each other. This means they capture DIFFERENT sources of return. Combining uncorrelated factors gives better diversification.",
              "Compute the correlation between each factor's IC time series. High IC correlation = they make the same bets. Low = they complement each other.",
            ],
            checkpoint:
              "You can compute factor-factor correlations, assess redundancy, and explain why uncorrelated factors are better for a multi-factor system.",
          },
          {
            num: 4,
            title: "Z-score normalization and composite scoring",
            tasks: [
              "Problem: size is measured in billions of RMB, P/B is a ratio, momentum is a percentage. You can't just add them. Solution: normalize to z-scores.",
              "For each factor, at each date, compute cross-sectional z-score: (value - mean) / std across all stocks. Now every factor is in the same units (standard deviations from mean).",
              "Combine: composite_score = w₁ × z_size + w₂ × z_value + w₃ × z_momentum. Start with equal weights (w = 1/3). You'll optimize later.",
              "Run quintile sorting on the composite score. Compare to each single-factor quintile sort. Does the combination outperform any individual factor?",
              "Compute IC for the composite. It should be higher and more stable than any single factor's IC if the factors are genuinely complementary.",
            ],
            checkpoint:
              "You can normalize factors to z-scores, combine them into a composite, and verify that the combination improves on individual factors.",
          },
          {
            num: 5,
            title: "Building the ranked watchlist",
            tasks: [
              "For the most recent date, compute composite factor scores for all stocks in your universe.",
              "Sort by composite score. The top-ranked stocks are your candidates: small, cheap, with strong momentum.",
              "For the top 20, pull recent price charts and any news. Sanity-check: do any look like value traps? Are any about to be delisted?",
              "This is NOT a buy list. This is a ranked output of your factor model. The backtesting in Phase 4 will tell you whether acting on these rankings is profitable after costs.",
              "Write a summary: which factors contributed most to the top stocks' scores? Are the top stocks concentrated in one sector, or diversified?",
            ],
            checkpoint:
              "You have a multi-factor ranking system that produces a scored and ranked list of 小盘股. You understand that this is analytical output, not a trading signal, until validated by backtesting.",
          },
          {
            num: 6,
            title: "Factor decay analysis (optional, bridges to Phase 4)",
            tasks: [
              "For each factor, compute IC at different horizons: 1-day, 1-week, 1-month, 3-month forward returns. How does IC change with horizon?",
              "Size factor usually decays slowly (market cap is stable). Momentum decays faster (trends eventually reverse). Value is somewhere in between.",
              "This tells you your optimal rebalancing frequency. If IC decays quickly, you need to rebalance more often, which increases costs.",
              "Map the trade-off: faster rebalancing = captures more of the factor's predictive power, but costs more. Slower = captures less, but cheaper. The optimal point depends on your transaction cost model (which you'll build in Project 7).",
            ],
            checkpoint:
              "You understand how factor predictive power decays over time and how this relates to rebalancing frequency and transaction costs.",
          },
        ],
        pitfalls: [
          "Using current fundamental data to sort historical stocks — same look-ahead bias as with market cap. Use POINT-IN-TIME data only.",
          "Not handling negative P/E stocks — excluding loss-making stocks from value sorts changes the universe in a non-random way. Document your choice and test sensitivity.",
          "Equal-weighting factors without considering IC stability — if one factor has a much more stable IC, it might deserve higher weight.",
          "Overfitting factor weights — optimizing weights on historical data will make the backtest look better but degrade out-of-sample. Start with equal weights.",
          "Concentration risk — your composite might rank an entire sector highly. Factor models can produce sector bets disguised as factor bets.",
        ],
        readyToMove: [
          "Can you implement and test a new factor from scratch (data → z-score → quintile sort → IC)?",
          "Can you explain the economic mechanism behind each factor you've implemented?",
          "Can you combine factors into a composite score and evaluate whether the combination is better than its parts?",
          "Do you understand factor decay and its implications for rebalancing frequency?",
        ],
        resources: [
          {
            title: "Barra Risk Factor Encyclopedia",
            note: "Industry-standard factor definitions. Use as reference for how professionals define size, value, momentum, quality, etc.",
          },
          {
            title: "Asness, Moskowitz, Pedersen: 'Value and Momentum Everywhere' (2013)",
            note: "Shows that value and momentum work across many markets (including China in extended studies). Focus on the China section if available.",
          },
        ],
        deliverable:
          "A factor ranking system that scores 小盘股 on multiple dimensions and produces a ranked watchlist.",
        connection:
          "You're now doing what the JoinQuant tutorial pointed toward but never taught: identifying, testing, and combining factors.",
      },
    ],
  },
  {
    id: "p4",
    title: "Phase 4",
    subtitle: "From Factor to Strategy",
    color: "#b91c1c",
    weeks: "Week 17–22",
    description:
      "You have factors that predict returns. Now you build them into an actual tradeable strategy, backtest it properly, and understand exactly where the backtest lies to you.",
    gateCheck: {
      title: "Before starting Phase 4",
      questions: [
        "Can you compute factor quintile returns and IC for any factor?",
        "Can you combine multiple factors into a composite score?",
        "Can you apply hypothesis testing to evaluate whether a factor is real?",
        "Do you have a multi-factor ranking system producing scored output?",
      ],
      ifNo:
        "Phase 4 turns your factor scores into trading decisions. If your factor evaluation is unreliable, your strategy will be built on unreliable inputs.",
    },
    projects: [
      {
        id: "p4a",
        title: "Project 7: Build a Backtester",
        time: "6–8 sessions",
        goal: "Build a simple backtesting engine from scratch. Not because existing ones are bad, but because understanding what a backtester does under the hood prevents you from being fooled by it.",
        builds: [
          "Event-driven vs vectorized backtesting (start with vectorized)",
          "Portfolio rebalancing logic: entry, exit, position sizing",
          "Transaction cost modeling: commissions, slippage, market impact",
          "Performance reporting: equity curve, drawdown, Sharpe, turnover",
        ],
        newConcepts: [
          "Look-ahead bias: the #1 backtesting error (using future information in past decisions)",
          "Survivorship bias: your stock universe shouldn't only include today's survivors",
          "Slippage in 小盘股: why your backtested fill price is unrealistic for illiquid stocks",
          "T+1 settlement rules and how they constrain intraday strategies in A-shares",
        ],
        sessions: [
          {
            num: 1,
            title: "Backtester architecture: vectorized approach",
            tasks: [
              "The idea: instead of simulating day-by-day, use matrix operations. You have a factor_scores matrix (dates × stocks) and a returns matrix (dates × stocks). The backtest is: at each rebalance date, form a portfolio from top-scoring stocks, then compute portfolio return = weighted average of stock returns.",
              "Build the skeleton: define rebalance dates (e.g., first trading day of each month). At each date, select top N stocks by composite score. Assign equal weights.",
              "Compute portfolio returns: for each day between rebalances, portfolio_return = sum(weight_i × return_i).",
              "Handle missing data: if a stock is suspended on a rebalance day, skip it. If a stock is suspended during a holding period, its return is 0 for that day (but you can't sell it).",
              "Output: a daily portfolio return series. Plot the equity curve using your risk_toolkit from Project 2.",
            ],
            checkpoint:
              "You have a basic backtester that takes factor scores and a returns matrix, and outputs a portfolio equity curve with no transaction costs.",
          },
          {
            num: 2,
            title: "Rebalancing logic and position sizing",
            tasks: [
              "Implement monthly rebalancing: on rebalance day, recompute scores, select top N stocks, sell those no longer in top N, buy new entrants.",
              "Track turnover: what fraction of the portfolio changes each rebalance? High turnover = high cost.",
              "Position sizing options: (1) equal weight (1/N per stock), (2) score-weighted (higher score = larger position), (3) risk-weighted (lower vol = larger position). Start with equal weight; it's the simplest and most robust.",
              "Implement a holding constraint: once you buy, hold for at least one rebalance period. This prevents excessive trading within a period.",
              "Test with different N (top 10, 20, 50 stocks). How does portfolio performance change? More stocks = more diversified but dilutes the factor signal.",
            ],
            checkpoint:
              "Your backtester handles rebalancing, tracks which stocks enter/exit, and computes turnover.",
          },
          {
            num: 3,
            title: "Transaction cost modeling: where backtests meet reality",
            tasks: [
              "Commission: A-share standard is ~0.025% per trade (买卖双向). Varies by broker. Add this to each trade.",
              "印花税 (stamp tax): 0.05% on sells only (as of recent regulations — verify current rate). This is fixed and unavoidable.",
              "Slippage: the difference between your intended price and actual execution price. For 小盘股, this is significant. Model it as a fixed fraction of the bid-ask spread.",
              "Market impact: large orders move the price. For a small retail account this is minimal, but for 小盘股 even small orders can impact thin order books. Model as a function of trade size / average daily volume.",
              "Implement: at each rebalance, subtract total transaction costs from the portfolio. Compare the equity curve with and without costs. The gap is your 'cost of implementation.'",
            ],
            checkpoint:
              "Your backtester includes a realistic cost model. You can quantify the difference between gross and net returns. For 小盘股 strategies, costs typically reduce Sharpe by 30-50%.",
          },
          {
            num: 4,
            title: "Performance reporting",
            tasks: [
              "Build a report function that takes a portfolio return series and outputs: total return, annualized return, annualized volatility, Sharpe ratio, Sortino ratio, max drawdown, max drawdown duration, turnover.",
              "Add a benchmark comparison: compute the same metrics for the 中证1000 index. Your strategy should be compared to the relevant index, not to zero.",
              "Compute alpha: strategy return minus benchmark return. Is your factor model adding value after costs, relative to just holding the index?",
              "Plot: equity curve vs benchmark, rolling Sharpe (1-year window), drawdown curve, monthly return heatmap.",
              "Generate the report for your multi-factor strategy from Project 6. This is the first real test of whether your factors are valuable.",
            ],
            checkpoint:
              "You can generate a full performance report with benchmark comparison, and you understand what each metric tells you about the strategy's viability.",
          },
          {
            num: 5,
            title: "Look-ahead bias audit",
            tasks: [
              "Go through your entire pipeline and list every point where information from the future could leak in. Common sources: (1) using current index constituents to define the historical universe, (2) using market cap or fundamentals from after the decision date, (3) using adjusted prices that incorporate future events.",
              "For each source, assess: is it present in your code? If yes, fix it. If you can't fix it (e.g., your data source doesn't provide historical index membership), document the bias and estimate its impact.",
              "Test: shift all your factor data forward by one month. If performance improves, you might have look-ahead bias (because the 'future' factor values are more predictive of future returns than the 'current' ones, and both are in the future relative to the decision date).",
              "T+1 settlement: in A-shares, you can't sell a stock the same day you buy it. If your backtester allows this, you're implicitly using T+0, which doesn't exist for retail investors.",
              "Write a bias audit document: list every known bias in your backtest, its estimated impact, and whether it inflates or deflates reported performance.",
            ],
            checkpoint:
              "You have audited your backtester for look-ahead bias and documented all known biases. You can explain why backtested performance is almost always better than live performance.",
          },
          {
            num: 6,
            title: "Slippage deep-dive for 小盘股",
            tasks: [
              "Pull intraday or tick data for a few 小盘股 (if available). If not, use daily data with volume to estimate liquidity.",
              "Compute average daily turnover (成交额) for your universe. Stocks with low turnover will have high slippage.",
              "Model the Amihud illiquidity measure: |daily return| / daily volume (in RMB). Higher = more illiquid.",
              "Filter your stock universe: exclude stocks below a minimum daily turnover threshold (e.g., < 5M RMB/day). Re-run your backtest. How much performance changes tells you how much of your backtest relied on illiquid stocks.",
              "This is the key tension for 小盘股 strategies: the most inefficient stocks are the most illiquid. The alpha is highest where execution is hardest.",
            ],
            checkpoint:
              "You can quantify liquidity, filter by it, and assess how much of your backtested performance comes from illiquid stocks that would be hard to trade in practice.",
          },
          {
            num: 7,
            title: "Integration: full strategy backtest",
            tasks: [
              "Combine everything: multi-factor scores (Project 6) → stock selection → portfolio construction → rebalancing → cost model → performance reporting.",
              "Run the full backtest over your sample period. Generate the report.",
              "Compare to benchmark. Is there alpha after costs? How does Sharpe compare to the index?",
              "Identify the worst drawdown period. What happened in the market during that period? Was it a broad market crash or a factor-specific drawdown?",
              "Write a one-page summary: strategy description, performance summary, known biases and limitations, and your honest assessment of whether this is worth paper-trading.",
            ],
            checkpoint:
              "You have a complete, end-to-end backtested strategy with honest cost modeling and bias documentation.",
          },
          {
            num: 8,
            title: "Event-driven backtester (optional, advanced)",
            tasks: [
              "Vectorized backtesting can't handle certain scenarios: conditional orders, stop losses, risk limits hit mid-period, or intraday signals.",
              "Build a simple event-driven loop: for each day, check signals, execute orders, update portfolio, record state.",
              "Add a stop loss: if a position drops more than X%, sell it at the next day's open (respecting T+1). Re-run the backtest. Does the stop loss help or hurt?",
              "Compare results to your vectorized backtest. They should be close if you did the vectorized one correctly. If they differ, debug to find the discrepancy.",
            ],
            checkpoint:
              "You understand the trade-offs between vectorized (fast, simple) and event-driven (flexible, realistic) backtesting, and can build a basic version of each.",
          },
        ],
        pitfalls: [
          "Building the backtester without costs and then 'adding costs later' — costs change which strategies work. Always include costs from the first test.",
          "Using T+0 in backtests when A-shares have T+1 — this inflates performance for any strategy with frequent trading.",
          "Not tracking turnover — you can't know if a strategy is realistic without knowing how much trading it requires.",
          "Testing many parameter combinations and reporting the best one — this is overfitting the backtest. You'll address this properly in Project 8.",
        ],
        readyToMove: [
          "Can you run a full backtest with costs and generate a performance report?",
          "Can you list the known biases in your backtest and estimate their impact?",
          "Can you explain why backtested performance almost always exceeds live performance?",
          "Is your backtester flexible enough to test different factor combinations and parameters?",
        ],
        resources: [
          {
            title: "de Prado: Advances in Financial Machine Learning, Ch. 10-12",
            note: "Chapters on backtesting pitfalls. Dense but directly applicable. Focus on the taxonomy of backtest errors.",
          },
          {
            title: "Your own risk_toolkit.py and factor code from Phases 1-3",
            note: "The backtester depends on every tool you've built so far. If anything is unreliable, fix it before building on it.",
          },
        ],
        deliverable:
          "A backtesting module that takes your factor scores from Project 6, simulates a monthly rebalancing strategy, and reports realistic performance.",
        connection:
          "JoinQuant's backtest report gave you numbers. Now you know what assumptions those numbers depend on, and you can stress-test those assumptions yourself.",
      },
      {
        id: "p4b",
        title: "Project 8: Strategy Evaluation & Paper Trading",
        time: "4–6 sessions",
        goal: "Critically evaluate your strategy. Run out-of-sample tests. Set up a paper trading protocol. Decide whether this strategy is worth risking real money on.",
        builds: [
          "In-sample vs out-of-sample testing (train/test split for strategies)",
          "Walk-forward analysis: the right way to evaluate time-series strategies",
          "Monte Carlo simulation: how bad could it get?",
          "Paper trading setup and tracking spreadsheet",
        ],
        newConcepts: [
          "Overfitting: the gap between in-sample and out-of-sample is your measure of self-deception",
          "Regime dependence: bull-market strategies die in bear markets",
          "Capacity constraints: works for 100K RMB but not for 10M RMB",
          "Psychological discipline: following a system when it's losing money",
        ],
        sessions: [
          {
            num: 1,
            title: "In-sample vs out-of-sample split",
            tasks: [
              "Split your data: first 70% = in-sample (training), last 30% = out-of-sample (testing). Never touch the test set while developing.",
              "Run your strategy on in-sample only. Record all metrics.",
              "Now run on out-of-sample. Compare: Sharpe, max drawdown, factor IC. The gap between in-sample and out-of-sample performance is your overfitting measure.",
              "If out-of-sample Sharpe is less than half of in-sample Sharpe, you've probably overfit. Go back and simplify.",
              "Important: you only get ONE shot at out-of-sample. If you adjust the strategy and re-test, the out-of-sample becomes in-sample. This is why discipline matters.",
            ],
            checkpoint:
              "You understand train/test splitting for strategies and can measure the overfitting gap.",
          },
          {
            num: 2,
            title: "Walk-forward analysis: more realistic than a single split",
            tasks: [
              "A single split depends on where you cut. Walk-forward fixes this: (1) train on years 1-3, test on year 4. (2) Train on years 1-4, test on year 5. (3) Continue rolling forward.",
              "Implement: for each test year, re-compute factor scores using only data available up to the start of that year. Run the strategy. Record performance.",
              "Combine all test-year results into a single performance series. This is a fairer estimate of live performance.",
              "Compare walk-forward results to your full-sample backtest. Walk-forward will look worse. The difference is the cost of realistic evaluation.",
              "Check: are there years where the strategy loses badly? What was happening in the market? This identifies regime dependence.",
            ],
            checkpoint:
              "You can run walk-forward analysis and interpret results. You understand that walk-forward performance is the most honest predictor of live performance.",
          },
          {
            num: 3,
            title: "Monte Carlo simulation: stress testing",
            tasks: [
              "Take your strategy's daily returns. Resample them with replacement to create 1,000 synthetic equity curves.",
              "For each synthetic curve, compute max drawdown and terminal wealth. You now have a DISTRIBUTION of possible outcomes.",
              "Find the 5th percentile of outcomes: this is your 'bad case' scenario. Is it survivable? If the 5th percentile drawdown is 60%, can you stomach that?",
              "Add a twist: block bootstrap (resample in chunks of 20 days, not individual days) to preserve the serial correlation structure. Compare results.",
              "This isn't prediction. It's asking: 'if the future has similar statistical properties to the past, what's the range of outcomes I should expect?'",
            ],
            checkpoint:
              "You can run a Monte Carlo simulation on strategy returns and interpret the distribution of outcomes. You understand that the backtest is one path; reality could be any of these paths.",
          },
          {
            num: 4,
            title: "The strategy report: everything in one document",
            tasks: [
              "Write a comprehensive strategy report. Sections: (1) Thesis and economic mechanism, (2) Factor definitions and rationale, (3) In-sample results, (4) Out-of-sample results, (5) Walk-forward results, (6) Monte Carlo stress test, (7) Known biases and limitations, (8) Transaction cost analysis, (9) Conclusion and recommendation.",
              "Be honest. If the strategy doesn't work after costs, say so. A 'negative result' is still valuable — you know not to trade it.",
              "Compare your strategy to the simplest alternative: buy and hold 中证1000 ETF. If your strategy can't beat this after costs and effort, the effort isn't worth it.",
              "Include a 'what would change my mind' section: what market conditions would make you stop trading this strategy?",
            ],
            checkpoint:
              "You have a complete, honest strategy report that you'd be comfortable showing to a skeptical peer.",
          },
          {
            num: 5,
            title: "Paper trading setup",
            tasks: [
              "Create a tracking spreadsheet: date, signal (which stocks to buy/sell), intended price, actual fill price (for paper trading, use next day's open), portfolio state, daily P&L.",
              "Set monitoring rules: (1) if drawdown exceeds X%, pause and review. (2) If monthly performance deviates from backtest by more than Y standard deviations, investigate. (3) Review after 3 months regardless.",
              "Define success and failure criteria before you start: 'I will consider paper trading successful if after 3 months, the strategy's Sharpe is within 50% of the backtest Sharpe and max drawdown hasn't exceeded the Monte Carlo 10th percentile.'",
              "Run the first week of paper trading. Compare actual signals to what your backtest would have produced. Any discrepancies indicate implementation bugs.",
              "The psychological test: can you follow the system when it tells you to buy a stock that's been falling? Paper trading with real tracking (even without money) surfaces discipline issues.",
            ],
            checkpoint:
              "You have a paper trading protocol with predefined success/failure criteria, a tracking system, and you've verified that your signals match the backtest.",
          },
          {
            num: 6,
            title: "Regime analysis preview (optional, bridges to Phase 5+)",
            tasks: [
              "Partition your backtest into 'regimes': bull market (index rising), bear market (index falling), high volatility, low volatility. Use simple rules like 200-day moving average above/below.",
              "Compute your strategy's metrics in each regime separately. Most factor strategies work well in one regime and poorly in another.",
              "This is the preview: advanced work involves dynamically adjusting factor weights based on the detected regime. For now, just document the dependency.",
              "Write a forward-looking plan: based on everything you've learned, what would you focus on next? More factors? Better cost modeling? Regime detection? Machine learning?",
            ],
            checkpoint:
              "You understand how your strategy performs across different market regimes and have a plan for what to learn next.",
          },
        ],
        pitfalls: [
          "Re-using the out-of-sample set — once you've seen out-of-sample results and changed the strategy, the data is no longer out-of-sample. Walk-forward analysis is better for iterative development.",
          "Ignoring the gap between in-sample and out-of-sample — this gap is information. A large gap means you've overfit. Treat it as a diagnostic, not an inconvenience.",
          "Monte Carlo with independent resampling when returns are serially correlated — block bootstrap is more realistic. The cluster structure of returns matters for drawdown estimation.",
          "Setting paper trading criteria after seeing results — this is the same as p-hacking. Define criteria before you start.",
        ],
        readyToMove: [
          "Can you critically evaluate a strategy using out-of-sample and walk-forward analysis?",
          "Can you run a Monte Carlo stress test and interpret the distribution of outcomes?",
          "Have you written an honest strategy report with known limitations?",
          "Do you have a paper trading protocol with predefined success/failure criteria?",
        ],
        resources: [
          {
            title: "Bailey & de Prado: 'The Deflated Sharpe Ratio' (2014)",
            note: "How to adjust the Sharpe ratio for multiple testing when you've tried many strategies. Technical but the key insight is accessible.",
          },
          {
            title: "Your complete codebase from Projects 0-7",
            note: "This project ties everything together. If any prior tool is broken, it will show up here.",
          },
        ],
        deliverable:
          "A complete strategy report with in-sample, out-of-sample, walk-forward results, risk analysis, and a paper trading plan.",
        connection:
          "This is the end-to-end pipeline: from 'I have a thesis about 小盘股' to 'here is a tested, evaluated strategy with known limitations.'",
      },
    ],
  },
];

const ALREADY_KNOW = [
  "JoinQuant platform mechanics: initialize(), handle_data(), context",
  "Basic Python: variables, loops, conditionals, functions, lists, dicts",
  "JoinQuant API: order(), get_price(), get_fundamentals()",
  "Concept of 回测 (backtesting) and how to run one on JoinQuant",
  "Evaluation metrics exist: 年化收益, 最大回撤, 夏普比率 (surface-level)",
  "Warnings about 过拟合, 未来函数, 策略失效 (conceptual, not yet applied)",
];

const GAP = [
  "How to identify a factor and translate a trading idea into testable code",
  "Statistical foundations: distributions, hypothesis testing, significance",
  "Working with data independently (outside JoinQuant's walled garden)",
  "Understanding WHY metrics like Sharpe ratio work and when they mislead",
  "Backtesting methodology: what can go wrong between backtest and live",
  "小盘股 microstructure: liquidity, price limits, information diffusion",
];

// ─── COMPONENTS ─────────────────────────────────────────────

function ChevronDown({ open }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 20 20"
      fill="none"
      style={{
        transform: open ? "rotate(180deg)" : "rotate(0deg)",
        transition: "transform 0.2s ease",
        flexShrink: 0,
      }}
    >
      <path
        d="M5 7.5L10 12.5L15 7.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ProgressDot({ done, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: 18,
        height: 18,
        borderRadius: "50%",
        border: done ? "none" : "2px solid #ccc",
        background: done ? "#16a34a" : "transparent",
        cursor: "pointer",
        padding: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        transition: "all 0.15s ease",
      }}
      title={done ? "Mark incomplete" : "Mark complete"}
    >
      {done && (
        <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
          <path d="M2 6L5 9L10 3" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  );
}

function SessionItem({ session, projectId, progress, setProgress }) {
  const key = `${projectId}-s${session.num}`;
  const done = progress[key] || false;

  const toggle = () => {
    const next = { ...progress, [key]: !done };
    setProgress(next);
    saveProgress(next);
  };

  return (
    <div
      style={{
        padding: "10px 0",
        borderBottom: "1px solid rgba(0,0,0,0.05)",
      }}
    >
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <div style={{ paddingTop: 2 }}>
          <ProgressDot done={done} onClick={toggle} />
        </div>
        <div style={{ flex: 1 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: done ? "#16a34a" : "var(--text-primary)",
              marginBottom: 4,
              textDecoration: done ? "line-through" : "none",
              opacity: done ? 0.7 : 1,
            }}
          >
            Session {session.num}: {session.title}
          </div>
          <div style={{ fontSize: 12.5, lineHeight: 1.7, color: "var(--text-secondary)" }}>
            {session.tasks.map((task, i) => (
              <div key={i} style={{ marginBottom: 3, paddingLeft: 14, position: "relative" }}>
                <span style={{ position: "absolute", left: 0, color: "var(--text-tertiary)", fontSize: 11 }}>
                  {i + 1}.
                </span>
                {task}
              </div>
            ))}
          </div>
          <div
            style={{
              marginTop: 8,
              padding: "6px 10px",
              background: "rgba(22, 163, 74, 0.06)",
              borderRadius: 5,
              fontSize: 12,
              color: "#15803d",
              borderLeft: "3px solid rgba(22, 163, 74, 0.3)",
            }}
          >
            <span style={{ fontWeight: 600 }}>Checkpoint:</span> {session.checkpoint}
          </div>
        </div>
      </div>
    </div>
  );
}

function CollapsibleSection({ title, color, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginBottom: 6 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          width: "100%",
          padding: "8px 10px",
          background: `${color}08`,
          border: `1px solid ${color}22`,
          borderRadius: 6,
          cursor: "pointer",
          fontSize: 11.5,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: color,
          textAlign: "left",
        }}
      >
        {title}
        <span style={{ marginLeft: "auto" }}>
          <ChevronDown open={open} />
        </span>
      </button>
      {open && (
        <div style={{ padding: "8px 12px 4px" }}>{children}</div>
      )}
    </div>
  );
}

function ProjectCard({ project, phaseColor, progress, setProgress }) {
  const [open, setOpen] = useState(false);

  const totalSessions = project.sessions.length;
  const completedSessions = project.sessions.filter(
    (s) => progress[`${project.id}-s${s.num}`]
  ).length;

  return (
    <div
      style={{
        border: "1px solid var(--border-color)",
        borderRadius: 10,
        marginBottom: 12,
        overflow: "hidden",
        background: "var(--card-bg)",
      }}
    >
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          width: "100%",
          padding: "14px 16px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <div
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: completedSessions === totalSessions ? "#16a34a" : phaseColor,
            marginTop: 7,
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1 }}>
          <div
            style={{
              fontSize: 14.5,
              fontWeight: 600,
              color: "var(--text-primary)",
              marginBottom: 4,
            }}
          >
            {project.title}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
              {project.time}
            </span>
            {completedSessions > 0 && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: completedSessions === totalSessions ? "#16a34a" : phaseColor,
                  background: completedSessions === totalSessions ? "rgba(22,163,74,0.1)" : `${phaseColor}12`,
                  padding: "1px 7px",
                  borderRadius: 10,
                }}
              >
                {completedSessions}/{totalSessions}
              </span>
            )}
          </div>
        </div>
        <ChevronDown open={open} />
      </button>

      {open && (
        <div
          style={{
            padding: "0 16px 16px 34px",
            fontSize: 13,
            lineHeight: 1.7,
            color: "var(--text-secondary)",
          }}
        >
          <p style={{ marginBottom: 14, fontStyle: "italic", color: "var(--text-tertiary)", fontSize: 13 }}>
            {project.goal}
          </p>

          {/* Sessions */}
          <CollapsibleSection title={`Sessions (${completedSessions}/${totalSessions} complete)`} color={phaseColor} defaultOpen={true}>
            {project.sessions.map((s) => (
              <SessionItem
                key={s.num}
                session={s}
                projectId={project.id}
                progress={progress}
                setProgress={setProgress}
              />
            ))}
          </CollapsibleSection>

          {/* Skills + Concepts */}
          <CollapsibleSection title="Skills you'll build" color={phaseColor}>
            {project.builds.map((b, i) => (
              <div key={i} style={{ marginBottom: 3, paddingLeft: 12, position: "relative", fontSize: 12.5 }}>
                <span style={{ position: "absolute", left: 0, color: "var(--text-tertiary)" }}>·</span>
                {b}
              </div>
            ))}
          </CollapsibleSection>

          <CollapsibleSection title="New concepts" color={phaseColor}>
            {project.newConcepts.map((c, i) => (
              <div key={i} style={{ marginBottom: 3, paddingLeft: 12, position: "relative", fontSize: 12.5 }}>
                <span style={{ position: "absolute", left: 0, color: "var(--text-tertiary)" }}>·</span>
                {c}
              </div>
            ))}
          </CollapsibleSection>

          {/* Pitfalls */}
          {project.pitfalls && (
            <CollapsibleSection title="Common pitfalls" color="#dc2626">
              {project.pitfalls.map((p, i) => (
                <div key={i} style={{ marginBottom: 6, paddingLeft: 12, position: "relative", fontSize: 12.5 }}>
                  <span style={{ position: "absolute", left: 0, color: "#dc2626" }}>⚠</span>
                  {p}
                </div>
              ))}
            </CollapsibleSection>
          )}

          {/* Ready to Move On */}
          {project.readyToMove && (
            <CollapsibleSection title="Ready to move on?" color="#16a34a">
              <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 6 }}>
                Answer yes to all of these before proceeding to the next project:
              </div>
              {project.readyToMove.map((q, i) => (
                <div key={i} style={{ marginBottom: 4, paddingLeft: 12, position: "relative", fontSize: 12.5 }}>
                  <span style={{ position: "absolute", left: 0 }}>□</span>
                  {q}
                </div>
              ))}
            </CollapsibleSection>
          )}

          {/* Resources */}
          {project.resources && (
            <CollapsibleSection title="Resources" color="#6b7280">
              {project.resources.map((r, i) => (
                <div key={i} style={{ marginBottom: 8, fontSize: 12.5 }}>
                  <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{r.title}</div>
                  <div style={{ color: "var(--text-tertiary)", fontSize: 12 }}>{r.note}</div>
                </div>
              ))}
            </CollapsibleSection>
          )}

          {/* Deliverable */}
          <div
            style={{
              padding: "10px 14px",
              background: "rgba(0,0,0,0.03)",
              borderRadius: 6,
              marginTop: 10,
              marginBottom: 8,
              borderLeft: `3px solid ${phaseColor}`,
              fontSize: 12.5,
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: phaseColor,
                marginBottom: 4,
              }}
            >
              Deliverable
            </div>
            {project.deliverable}
          </div>

          <div style={{ fontSize: 12, color: "var(--text-tertiary)", fontStyle: "italic" }}>
            ↳ {project.connection}
          </div>
        </div>
      )}
    </div>
  );
}

function GateCheck({ gate }) {
  const [open, setOpen] = useState(false);
  if (!gate) return null;

  return (
    <div style={{ marginBottom: 12 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "10px 14px",
          background: "rgba(251, 146, 60, 0.08)",
          border: "1px solid rgba(251, 146, 60, 0.25)",
          borderRadius: 8,
          cursor: "pointer",
          fontSize: 12.5,
          fontWeight: 600,
          color: "#c2410c",
          textAlign: "left",
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
          <path d="M8 1v8M8 12v1" stroke="#c2410c" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        {gate.title}
        <span style={{ marginLeft: "auto" }}>
          <ChevronDown open={open} />
        </span>
      </button>
      {open && (
        <div
          style={{
            padding: "10px 16px 10px 38px",
            fontSize: 12.5,
            lineHeight: 1.7,
            color: "var(--text-secondary)",
          }}
        >
          {gate.questions.map((q, i) => (
            <div key={i} style={{ marginBottom: 3 }}>
              <span style={{ color: "#c2410c", marginRight: 6 }}>□</span>
              {q}
            </div>
          ))}
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              color: "#c2410c",
              fontStyle: "italic",
            }}
          >
            If not: {gate.ifNo}
          </div>
        </div>
      )}
    </div>
  );
}

function DiagnosticSection() {
  const [showKnow, setShowKnow] = useState(false);
  const [showGap, setShowGap] = useState(false);

  return (
    <div style={{ marginBottom: 36 }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, color: "var(--text-primary)", marginBottom: 8 }}>
        Where You Are Now
      </h2>
      <p style={{ fontSize: 13.5, lineHeight: 1.7, color: "var(--text-secondary)", marginBottom: 14 }}>
        Based on the JoinQuant 新手入门教程 you completed and our conversations.
      </p>

      <button
        onClick={() => setShowKnow(!showKnow)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "10px 14px",
          background: "rgba(34, 197, 94, 0.07)",
          border: "1px solid rgba(34, 197, 94, 0.2)",
          borderRadius: 8,
          cursor: "pointer",
          fontSize: 13,
          fontWeight: 600,
          color: "#16a34a",
          marginBottom: 8,
          textAlign: "left",
        }}
      >
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#16a34a", flexShrink: 0 }} />
        What you already have
        <span style={{ marginLeft: "auto" }}><ChevronDown open={showKnow} /></span>
      </button>
      {showKnow && (
        <div style={{ padding: "8px 16px 8px 30px", marginBottom: 8, fontSize: 12.5, lineHeight: 1.8, color: "var(--text-secondary)" }}>
          {ALREADY_KNOW.map((item, i) => (
            <div key={i} style={{ marginBottom: 3 }}>
              <span style={{ color: "#16a34a", marginRight: 8 }}>✓</span>{item}
            </div>
          ))}
        </div>
      )}

      <button
        onClick={() => setShowGap(!showGap)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "10px 14px",
          background: "rgba(239, 68, 68, 0.05)",
          border: "1px solid rgba(239, 68, 68, 0.18)",
          borderRadius: 8,
          cursor: "pointer",
          fontSize: 13,
          fontWeight: 600,
          color: "#dc2626",
          textAlign: "left",
        }}
      >
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#dc2626", flexShrink: 0 }} />
        What you're missing (this plan fills these)
        <span style={{ marginLeft: "auto" }}><ChevronDown open={showGap} /></span>
      </button>
      {showGap && (
        <div style={{ padding: "8px 16px 8px 30px", marginBottom: 8, fontSize: 12.5, lineHeight: 1.8, color: "var(--text-secondary)" }}>
          {GAP.map((item, i) => (
            <div key={i} style={{ marginBottom: 3 }}>
              <span style={{ color: "#dc2626", marginRight: 8 }}>→</span>{item}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PhaseBlock({ phase, progress, setProgress }) {
  const allSessions = phase.projects.flatMap((p) =>
    p.sessions.map((s) => `${p.id}-s${s.num}`)
  );
  const completedInPhase = allSessions.filter((k) => progress[k]).length;

  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <span
          style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 11,
            fontWeight: 700,
            color: phase.color,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            whiteSpace: "nowrap",
          }}
        >
          {phase.weeks}
        </span>
        <h3 style={{ fontSize: 19, fontWeight: 600, color: "var(--text-primary)", margin: 0 }}>
          {phase.title}: {phase.subtitle}
        </h3>
      </div>

      {/* Phase progress bar */}
      {allSessions.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, marginLeft: 2 }}>
          <div style={{ flex: 1, height: 3, background: "#e5e5e5", borderRadius: 2, overflow: "hidden" }}>
            <div
              style={{
                width: `${(completedInPhase / allSessions.length) * 100}%`,
                height: "100%",
                background: phase.color,
                borderRadius: 2,
                transition: "width 0.3s ease",
              }}
            />
          </div>
          <span style={{ fontSize: 11, color: "var(--text-tertiary)", fontFamily: "'IBM Plex Mono', monospace" }}>
            {completedInPhase}/{allSessions.length}
          </span>
        </div>
      )}

      <p style={{ fontSize: 13, lineHeight: 1.7, color: "var(--text-secondary)", marginBottom: 14, marginLeft: 2 }}>
        {phase.description}
      </p>

      <GateCheck gate={phase.gateCheck} />

      {phase.projects.map((p) => (
        <ProjectCard
          key={p.id}
          project={p}
          phaseColor={phase.color}
          progress={progress}
          setProgress={setProgress}
        />
      ))}
    </div>
  );
}

// ─── MAIN ───────────────────────────────────────────────────

export default function LearningPlan() {
  const [progress, setProgress] = useState({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadProgress().then((p) => {
      setProgress(p);
      setLoaded(true);
    });
  }, []);

  const totalSessions = PHASES.flatMap((ph) =>
    ph.projects.flatMap((p) => p.sessions)
  ).length;
  const completedTotal = Object.values(progress).filter(Boolean).length;

  const resetProgress = useCallback(async () => {
    if (confirm("Reset all progress? This cannot be undone.")) {
      setProgress({});
      await saveProgress({});
    }
  }, []);

  if (!loaded) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "#888" }}>
        Loading progress...
      </div>
    );
  }

  return (
    <div
      style={{
        "--text-primary": "#1a1a1a",
        "--text-secondary": "#4a4a4a",
        "--text-tertiary": "#888",
        "--border-color": "#e5e5e5",
        "--card-bg": "#fafafa",
        maxWidth: 720,
        margin: "0 auto",
        padding: "28px 20px",
        fontFamily: "'IBM Plex Sans', -apple-system, sans-serif",
      }}
    >
      <link
        href="https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;700&display=swap"
        rel="stylesheet"
      />

      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <h1
          style={{
            fontFamily: "'Source Serif 4', Georgia, serif",
            fontSize: 26,
            fontWeight: 700,
            color: "var(--text-primary)",
            marginBottom: 4,
            lineHeight: 1.2,
          }}
        >
          Quant Trading Learning Plan
        </h1>
        <p
          style={{
            fontFamily: "'Source Serif 4', Georgia, serif",
            fontSize: 15,
            color: "var(--text-tertiary)",
            margin: 0,
          }}
        >
          小盘股 Quantitative Analysis — From Data to Strategy
        </p>

        {/* Overall progress */}
        <div
          style={{
            marginTop: 14,
            padding: "12px 16px",
            background: "rgba(37, 99, 235, 0.04)",
            border: "1px solid rgba(37, 99, 235, 0.12)",
            borderRadius: 8,
            fontSize: 13,
            lineHeight: 1.7,
            color: "var(--text-secondary)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span>
              <strong>Progress:</strong> {completedTotal} of {totalSessions} sessions complete
            </span>
            {completedTotal > 0 && (
              <button
                onClick={resetProgress}
                style={{
                  fontSize: 11,
                  color: "#dc2626",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  textDecoration: "underline",
                }}
              >
                Reset
              </button>
            )}
          </div>
          <div style={{ height: 4, background: "#e5e5e5", borderRadius: 2, overflow: "hidden" }}>
            <div
              style={{
                width: `${(completedTotal / totalSessions) * 100}%`,
                height: "100%",
                background: "#2563eb",
                borderRadius: 2,
                transition: "width 0.3s ease",
              }}
            />
          </div>
          <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--text-tertiary)" }}>
            9 projects across 5 phases. Each session is ~1.5 hours. Tap any project to see session-by-session instructions. Mark sessions complete to track your progress.
          </div>
        </div>
      </div>

      <DiagnosticSection />

      <h2
        style={{
          fontFamily: "'Source Serif 4', Georgia, serif",
          fontSize: 20,
          fontWeight: 600,
          color: "var(--text-primary)",
          marginBottom: 18,
        }}
      >
        The Roadmap
      </h2>

      {PHASES.map((phase) => (
        <PhaseBlock
          key={phase.id}
          phase={phase}
          progress={progress}
          setProgress={setProgress}
        />
      ))}

      {/* After Phase 4 */}
      <div
        style={{
          marginTop: 20,
          padding: "14px 18px",
          background: "rgba(0,0,0,0.02)",
          borderRadius: 10,
          border: "1px solid var(--border-color)",
        }}
      >
        <h3
          style={{
            fontFamily: "'Source Serif 4', Georgia, serif",
            fontSize: 16,
            fontWeight: 600,
            color: "var(--text-primary)",
            marginBottom: 8,
          }}
        >
          After Phase 4
        </h3>
        <p style={{ fontSize: 13, lineHeight: 1.7, color: "var(--text-secondary)", margin: 0 }}>
          By this point you'll have the skills and judgment to direct your own
          learning. Likely next steps include regime detection (bull/bear
          adaptation), portfolio construction across multiple strategies,
          execution optimization, and machine learning for factor discovery.
          We'll decide together based on what you've learned and what your
          results reveal.
        </p>
      </div>

      <div
        style={{
          marginTop: 16,
          padding: "10px 14px",
          background: "rgba(180, 83, 9, 0.05)",
          border: "1px solid rgba(180, 83, 9, 0.18)",
          borderRadius: 8,
          fontSize: 12,
          lineHeight: 1.7,
          color: "var(--text-secondary)",
        }}
      >
        <strong style={{ color: "#b45309" }}>Timeline:</strong>{" "}
        ~22 weeks at 2-3 sessions per week. Some projects will go faster, some will stall.
        This is a sequence, not a schedule. If you want to skip ahead, tell me
        and I'll flag prerequisites.
      </div>
    </div>
  );
}
