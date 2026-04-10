const REFRESH_MS = 2000;
const NEWS_REFRESH_MS = 10000;
const HISTORY_REFRESH_MS = 4000;
const ANALYTICS_REFRESH_MS = 10000;

let selectedCoin = "ALL";
let availableCoins = [];
let watchlistSymbols = [];
let allCatalogSymbols = [];
let latestStatePayload = null;
let latestNewsPayload = { items: [], errors: [], generated_at: null };
let latestHistoryPayload = { items: [], count: 0, generated_at: null };
let newsSearchFilter = "";
let newsSourceFilter = "ALL";
let selectedBucketFilter = "ALL";

function setText(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value ?? "-";
}

function fmtNumber(value, digits = 6) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(digits);
}

function fmtPercent(value) {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${(num * 100).toFixed(2)}%`;
}

function fmtTime(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setCoinStatus(message, isError = false) {
  const el = document.getElementById("coin_status");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", Boolean(isError));
}

function normalizeSymbol(value) {
  return String(value ?? "").trim().toUpperCase();
}

function setNewsStatus(message, isError = false) {
  const el = document.getElementById("news_status");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", Boolean(isError));
}

function normalizeText(value) {
  return String(value ?? "").trim().toLowerCase();
}

function filteredTrade(trade) {
  if (!trade) return null;
  if (selectedCoin === "ALL") return trade;
  return trade.symbol === selectedCoin ? trade : null;
}

function filteredSnapshots(snapshots) {
  if (!Array.isArray(snapshots)) return [];
  if (selectedCoin === "ALL") return snapshots;
  return snapshots.filter((s) => s.symbol === selectedCoin);
}

function filteredPossibleTrades(trades) {
  if (!Array.isArray(trades)) return [];
  return trades.filter((trade) => {
    if (selectedCoin !== "ALL" && trade.symbol !== selectedCoin) return false;
    if (selectedBucketFilter !== "ALL" && trade.probability_bucket !== selectedBucketFilter) return false;
    return true;
  });
}

function filteredHistoryItems(items) {
  if (!Array.isArray(items)) return [];
  if (selectedCoin === "ALL") return items;
  return items.filter((row) => row.symbol === selectedCoin);
}

function bucketClass(bucket) {
  if (bucket === "ge_70") return "bucket-pill bucket-ge-70";
  if (bucket === "between_50_69") return "bucket-pill bucket-50-69";
  if (bucket === "between_30_49") return "bucket-pill bucket-30-49";
  if (bucket === "between_20_29") return "bucket-pill bucket-20-29";
  return "bucket-pill bucket-below-20";
}

function renderCategoryCards(categories) {
  const cat = categories || {};
  setText("cat_ge_70", cat.ge_70?.count ?? 0);
  setText("cat_50_69", cat.between_50_69?.count ?? 0);
  setText("cat_30_49", cat.between_30_49?.count ?? 0);
  setText("cat_20_29", cat.between_20_29?.count ?? 0);
  setText("cat_below_20", cat.below_20?.count ?? 0);
}

function renderMarketRows(snapshots) {
  const tbody = document.getElementById("market_rows");
  if (!tbody) return;

  if (!Array.isArray(snapshots) || snapshots.length === 0) {
    const msg = selectedCoin === "ALL" ? "Waiting for market data..." : `No market data for ${selectedCoin}`;
    tbody.innerHTML = `<tr><td colspan="3">${escapeHtml(msg)}</td></tr>`;
    return;
  }

  tbody.innerHTML = snapshots
    .map((row) => {
      const price = fmtNumber(row.price, row.price > 100 ? 2 : 6);
      const stamp = row.time ? new Date(row.time).toLocaleTimeString() : "-";
      return `<tr>
        <td>${escapeHtml(row.symbol ?? "-")}</td>
        <td>${price}</td>
        <td>${escapeHtml(stamp)}</td>
      </tr>`;
    })
    .join("");
}

function logLevelClass(level) {
  const clean = String(level || "INFO").toUpperCase();
  if (clean === "SUCCESS") return "log-level log-success";
  if (clean === "WARN") return "log-level log-warn";
  if (clean === "ACTION") return "log-level log-action";
  if (clean === "DANGER") return "log-level log-danger";
  return "log-level log-info";
}

function coinStatusClass(status) {
  if (status === "OPEN_TRADE") return "coin-status coin-open";
  if (status === "SIGNAL_FOUND") return "coin-status coin-signal";
  if (status === "MARKET_OK") return "coin-status coin-market";
  return "coin-status coin-idle";
}

function renderCoinActivity(state) {
  const tbody = document.getElementById("coin_activity_rows");
  if (!tbody) return;

  const snapshots = Array.isArray(state.market) ? state.market : [];
  const possibleTrades = Array.isArray(state.possible_trades) ? state.possible_trades : [];
  const liveTrades = possibleTrades.filter((trade) => String(trade.signal_state || "LIVE") === "LIVE");
  const openTrade = state.open_trade || {};
  const openSymbol = String(openTrade.signal_state || "").toUpperCase() === "LIVE" ? openTrade.symbol : null;

  const marketBySymbol = new Map();
  snapshots.forEach((row) => {
    if (!row || !row.symbol) return;
    marketBySymbol.set(row.symbol, row);
  });

  const signalCount = new Map();
  liveTrades.forEach((trade) => {
    const symbol = String(trade.symbol || "");
    if (!symbol) return;
    signalCount.set(symbol, (signalCount.get(symbol) || 0) + 1);
  });

  const symbols = new Set([...marketBySymbol.keys(), ...signalCount.keys()]);
  if (openSymbol) symbols.add(openSymbol);
  let rows = Array.from(symbols).sort((a, b) => a.localeCompare(b));
  if (selectedCoin !== "ALL") rows = rows.filter((symbol) => symbol === selectedCoin);

  const metaEl = document.getElementById("coin_activity_meta");
  if (metaEl) {
    metaEl.textContent = `Coins active: ${rows.length} | Open trade: ${openSymbol || "-"} | Live signals: ${liveTrades.length}`;
  }

  if (!rows.length) {
    const msg = selectedCoin === "ALL" ? "Waiting for coin activity..." : `No activity for ${selectedCoin}.`;
    tbody.innerHTML = `<tr><td colspan="5">${escapeHtml(msg)}</td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .slice(0, 200)
    .map((symbol) => {
      const row = marketBySymbol.get(symbol);
      const price = row ? fmtNumber(row.price, Number(row.price) > 100 ? 2 : 6) : "-";
      const tick = row?.time ? new Date(Number(row.time)).toLocaleTimeString() : "-";
      const signals = signalCount.get(symbol) || 0;
      let status = "MARKET_OK";
      let label = "MARKET_OK";
      if (!row) {
        status = "NO_DATA";
        label = "NO_DATA";
      }
      if (signals > 0) {
        status = "SIGNAL_FOUND";
        label = "SIGNAL_FOUND";
      }
      if (openSymbol && symbol === openSymbol) {
        status = "OPEN_TRADE";
        label = "OPEN_TRADE";
      }
      return `<tr>
        <td>${escapeHtml(symbol)}</td>
        <td>${price}</td>
        <td>${escapeHtml(tick)}</td>
        <td>${signals}</td>
        <td><span class="${coinStatusClass(status)}">${escapeHtml(label)}</span></td>
      </tr>`;
    })
    .join("");
}

function renderSystemLogs(events) {
  const tbody = document.getElementById("system_log_rows");
  if (!tbody) return;

  const rows = Array.isArray(events) ? events : [];
  const filtered = rows.filter((event) => {
    if (selectedCoin === "ALL") return true;
    const symbols = Array.isArray(event.symbols) ? event.symbols : [];
    if (symbols.includes(selectedCoin)) return true;
    return String(event.primary_symbol || "") === selectedCoin;
  });

  const metaEl = document.getElementById("system_log_meta");
  if (metaEl) {
    const last = filtered.length ? fmtTime(filtered[0].time) : "-";
    metaEl.textContent = `Events: ${rows.length} | Showing: ${filtered.length} | Last event: ${last}`;
  }

  if (!filtered.length) {
    const msg = selectedCoin === "ALL" ? "No runtime events captured yet." : `No runtime events for ${selectedCoin}.`;
    tbody.innerHTML = `<tr><td colspan="5">${escapeHtml(msg)}</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered
    .slice(0, 120)
    .map((event) => {
      const symbols = Array.isArray(event.symbols) ? event.symbols : [];
      const coinText = event.primary_symbol || symbols.slice(0, 3).join(", ") || "-";
      const level = String(event.severity || "INFO").toUpperCase();
      return `<tr>
        <td>${escapeHtml(fmtTime(event.time))}</td>
        <td>${escapeHtml(String(event.type || "-"))}</td>
        <td>${escapeHtml(coinText)}</td>
        <td>${escapeHtml(String(event.message || "-"))}</td>
        <td><span class="${logLevelClass(level)}">${escapeHtml(level)}</span></td>
      </tr>`;
    })
    .join("");
}

function renderPossibleRows(trades, meta, categories) {
  const tbody = document.getElementById("possible_rows");
  if (!tbody) return;

  const filtered = filteredPossibleTrades(trades || []);
  const metaEl = document.getElementById("possible_meta");
  renderCategoryCards(categories || {});
  if (metaEl) {
    const conf = fmtPercent(meta?.min_candidate_confidence);
    const exp = fmtNumber(meta?.min_candidate_expectancy_r, 3);
    const blocked = Array.isArray(meta?.blocked_symbols) ? meta.blocked_symbols.length : 0;
    const totalSeen = Number(meta?.total_candidates_seen ?? 0);
    const totalPossible = Number(meta?.total_possible_trades ?? 0);
    const limit = Number(meta?.possible_trades_limit ?? 0);
    const liveCount = Number(meta?.display_live_count ?? 0);
    const recentCount = Number(meta?.display_recent_count ?? 0);
    metaEl.textContent = `Filter: confidence >= ${conf}, expectancy >= ${exp}R | Candidates: ${totalSeen} | Possible: ${totalPossible} (limit ${limit}) | Displayed: LIVE ${liveCount}, RECENT ${recentCount} | Blocked: ${blocked}`;
  }

  if (!filtered.length) {
    const msg = selectedCoin === "ALL" ? "No qualifying opportunities for current filters." : `No opportunities for ${selectedCoin}.`;
    tbody.innerHTML = `<tr><td colspan="13">${escapeHtml(msg)}</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered
    .slice(0, 1000)
    .map((trade) => {
      const confNum = Number(trade.confidence);
      const confClass = Number.isFinite(confNum) && confNum >= 0.8 ? "confidence-high" : "confidence-mid";
      const side = String(trade.side || "-").toUpperCase();
      const sideClass = side === "LONG" ? "long" : side === "SHORT" ? "short" : "";
      const bucket = String(trade.probability_bucket || "below_20");
      const bucketLabel = String(trade.probability_bucket_label || "Loss-Likely");
      const signalState = String(trade.signal_state || "LIVE");
      return `<tr>
        <td>${escapeHtml(trade.symbol ?? "-")}</td>
        <td>${escapeHtml(trade.timeframe ?? "-")}</td>
        <td><span class="side-pill ${sideClass}">${escapeHtml(side)}</span></td>
        <td>${fmtNumber(trade.entry, 6)}</td>
        <td>${fmtNumber(trade.take_profit, 6)}</td>
        <td>${fmtNumber(trade.stop_loss, 6)}</td>
        <td class="${confClass}">${fmtPercent(trade.confidence)}</td>
        <td>${fmtPercent(trade.win_probability)}</td>
        <td>${escapeHtml(signalState)}</td>
        <td><span class="${bucketClass(bucket)}">${escapeHtml(bucketLabel)}</span></td>
        <td>${fmtNumber(trade.rr, 3)}</td>
        <td>${fmtNumber(trade.expectancy_r, 3)}</td>
        <td>${fmtNumber(trade.score, 4)}</td>
      </tr>`;
    })
    .join("");
}

function renderHistoryRows(historyPayload) {
  const tbody = document.getElementById("history_rows");
  if (!tbody) return;

  const payload = historyPayload || latestHistoryPayload;
  const allItems = Array.isArray(payload.items) ? payload.items : [];
  const items = filteredHistoryItems(allItems);
  const meta = document.getElementById("history_meta");
  if (meta) {
    const total = Number(payload.count ?? allItems.length);
    meta.textContent = `Stored trades: ${total} | Showing: ${items.length} | Last sync: ${fmtTime(payload.generated_at)}`;
  }

  if (!items.length) {
    const msg = selectedCoin === "ALL" ? "No stored trades yet." : `No stored trades for ${selectedCoin}.`;
    tbody.innerHTML = `<tr><td colspan="11">${escapeHtml(msg)}</td></tr>`;
    return;
  }

  tbody.innerHTML = items
    .slice(0, 500)
    .map((row) => {
      const side = String(row.side || "-").toUpperCase();
      const sideClass = side === "LONG" ? "long" : side === "SHORT" ? "short" : "";
      const closed = row.closed_at_ms ? new Date(Number(row.closed_at_ms)).toLocaleString() : fmtTime(row.event_time);
      const resultText = String(row.result ?? "-");
      const upper = resultText.toUpperCase();
      const isWin = upper.includes("WIN") || upper.startsWith("TP");
      const isLoss = upper.includes("LOSS") || upper.startsWith("SL");
      const resultPillClass = isWin ? "result-pill result-win" : isLoss ? "result-pill result-loss" : "result-pill";
      const rowClass = isWin ? "row-win" : isLoss ? "row-loss" : "";
      return `<tr class="${rowClass}">
        <td>${escapeHtml(closed)}</td>
        <td>${escapeHtml(row.symbol ?? "-")}</td>
        <td>${escapeHtml(row.timeframe ?? "-")}</td>
        <td><span class="side-pill ${sideClass}">${escapeHtml(side)}</span></td>
        <td>${fmtNumber(row.entry, 6)}</td>
        <td>${fmtNumber(row.exit_price, 6)}</td>
        <td>${fmtNumber(row.take_profit, 6)}</td>
        <td>${fmtNumber(row.stop_loss, 6)}</td>
        <td><span class="${resultPillClass}">${escapeHtml(resultText)}</span></td>
        <td>${fmtNumber(row.pnl_r, 4)}</td>
        <td>${fmtNumber(row.pnl_usd, 4)}</td>
      </tr>`;
    })
    .join("");
}

function renderState(state) {
  latestStatePayload = state;
  const coinLabel = selectedCoin === "ALL" ? "All Coins" : selectedCoin;
  setText("connection", `Last update: ${fmtTime(state.generated_at)} | View: ${coinLabel}`);

  const open = filteredTrade(state.open_trade) || {};
  const possibleTrades = Array.isArray(state.possible_trades) ? state.possible_trades : [];
  const focusTrade = open.symbol ? open : (filteredPossibleTrades(possibleTrades)[0] || {});
  const focusSymbol = focusTrade.symbol || open.symbol || "";
  const marketRows = Array.isArray(state.market) ? state.market : [];
  const marketMatch = marketRows.find((row) => row && row.symbol === focusSymbol) || null;
  const focusLabel = open.symbol ? "Live Trade" : focusTrade.symbol ? "Best Live Setup" : "Scanning";
  const focusStatusLine = open.symbol
    ? `${focusTrade.symbol} is currently open and being monitored live.`
    : focusTrade.symbol
      ? `No open trade yet. This is the clearest live candidate on the board.`
      : `No active trade or qualified setup for ${coinLabel} right now.`;

  setText("focus_label", focusLabel);
  setText("focus_label_repeat", focusLabel);
  setText("focus_status_line", focusStatusLine);
  setText("focus_market_price", marketMatch ? fmtNumber(marketMatch.price, Number(marketMatch.price) > 100 ? 2 : 6) : "-");
  setText("focus_market_price_repeat", marketMatch ? fmtNumber(marketMatch.price, Number(marketMatch.price) > 100 ? 2 : 6) : "-");
  setText("focus_reason", focusTrade.reason || "Waiting for the next qualifying trade explanation.");

  setText("pair", focusTrade.symbol || `No active trade (${coinLabel})`);
  setText("signal_state", focusTrade.signal_state || (open.symbol ? "LIVE" : focusTrade.symbol ? "SETUP" : "NONE"));
  setText("detail_signal_state", open.signal_state || "NONE");
  setText("signal_time", fmtTime(focusTrade.updated_at || focusTrade.time));
  setText("timeframe", focusTrade.timeframe || "-");
  setText("entry", fmtNumber(focusTrade.entry, 6));
  setText("tp", fmtNumber(focusTrade.take_profit, 6));
  setText("sl", fmtNumber(focusTrade.stop_loss, 6));
  setText("confidence", fmtPercent(focusTrade.confidence));
  setText("score", fmtNumber(focusTrade.score, 4));

  // Extra active trade fields
  const rrVal = Number.isFinite(+focusTrade.rr) && focusTrade.rr
    ? fmtNumber(focusTrade.rr, 3)
    : (Number.isFinite(+focusTrade.entry) && Number.isFinite(+focusTrade.take_profit) && Number.isFinite(+focusTrade.stop_loss) && +focusTrade.entry !== +focusTrade.stop_loss
        ? fmtNumber(Math.abs(+focusTrade.take_profit - +focusTrade.entry) / Math.abs(+focusTrade.entry - +focusTrade.stop_loss), 3)
        : "-");
  setText("open_rr", rrVal);
  setText("detail_open_rr", open.symbol ? rrVal : "-");
  setText("open_win_prob", fmtPercent(focusTrade.win_probability));
  setText("detail_open_win_prob", fmtPercent(open.win_probability));
  setText("open_ev", fmtNumber(focusTrade.expectancy_r, 4));
  setText("detail_open_ev", fmtNumber(open.expectancy_r, 4));
  setText("focus_score_repeat", fmtNumber(focusTrade.score, 4));

  const sideEl = document.getElementById("side");
  if (sideEl) {
    const side = (focusTrade.side || "-").toUpperCase();
    sideEl.textContent = side;
    sideEl.classList.remove("long", "short");
    if (side === "LONG") sideEl.classList.add("long");
    if (side === "SHORT") sideEl.classList.add("short");
  }

  const last = filteredTrade(state.last_trade) || {};
  setText("last_symbol", last.symbol || "-");
  setText("last_side", (last.side || "-").toUpperCase());
  setText("last_result", last.result || "-");
  setText("last_tf", last.timeframe || "-");
  setText("last_exit", fmtNumber(last.exit_price, 6));
  setText("last_pnl_r", fmtNumber(last.pnl_r, 4));
  setText("last_pnl_usd", fmtNumber(last.pnl_usd, 4));
  setText("last_closed", last.closed_at_ms ? new Date(last.closed_at_ms).toLocaleString() : "-");
  setText("last_reason", last.reason || "Waiting for first completed trade...");

  const lastBadgeEl = document.getElementById("last_result_badge");
  if (lastBadgeEl) {
    const resultText = String(last.result || "-");
    const upper = resultText.toUpperCase();
    lastBadgeEl.textContent = resultText;
    lastBadgeEl.className = "result-pill";
    if (upper.includes("WIN") || upper.startsWith("TP")) lastBadgeEl.classList.add("result-win");
    if (upper.includes("LOSS") || upper.startsWith("SL")) lastBadgeEl.classList.add("result-loss");
  }

  const summary = state.summary || {};
  setText("status", state.status || "-");
  setText("trades", summary.trades ?? "0");
  setText("wins", summary.wins ?? "0");
  setText("losses", summary.losses ?? "0");
  setText("win_rate", fmtPercent(summary.win_rate));
  setText("expectancy", fmtNumber(summary.expectancy_r, 4));
  const activeCount = Array.isArray(summary.active_symbols) ? summary.active_symbols.length : 0;
  const blockedCount = Array.isArray(summary.blocked_symbols) ? summary.blocked_symbols.length : 0;
  setText("active_symbols_count", activeCount);
  setText("blocked_symbols_count", blockedCount);

  // Win rate progress bar
  const wr = Number(summary.win_rate || 0);
  const bar = document.getElementById("win_rate_bar");
  if (bar) bar.style.width = `${(wr * 100).toFixed(1)}%`;
  setText("win_rate_label", fmtPercent(summary.win_rate));

  renderPossibleRows(
    state.possible_trades || [],
    state.possible_trades_meta || {},
    state.possible_probability_categories || {}
  );
  renderMarketRows(filteredSnapshots(state.market || []));
  renderCoinActivity(state);
  renderSystemLogs(state.recent_events || []);
  renderHistoryRows(latestHistoryPayload);
  renderGuardEvent(state.guard_event || null);
}

function renderGuardEvent(event) {
  if (!event || typeof event !== "object") {
    setText("guard_event_type", "No guard events yet.");
    setText("guard_event_detail", "Rolling symbol health and adaptive retuning status will appear here.");
    return;
  }

  const eventType = String(event.type || "GUARD_EVENT");
  const eventTime = fmtTime(event.time);
  setText("guard_event_type", `${eventType} @ ${eventTime}`);

  if (eventType === "SYMBOL_COOLDOWN_APPLIED") {
    const symbol = event.symbol || "-";
    const cycles = event.cooldown_cycles ?? "-";
    const stats = event.stats || {};
    setText(
      "guard_event_detail",
      `${symbol} cooled for ${cycles} cycles | win ${fmtPercent(stats.win_rate)} | exp ${fmtNumber(stats.expectancy_r, 4)}R`
    );
    return;
  }

  if (eventType === "GUARD_RETUNE") {
    const direction = event.direction || "-";
    const updated = event.updated || {};
    setText(
      "guard_event_detail",
      `${direction} filters: conf ${fmtPercent(updated.min_candidate_confidence)}, rr ${fmtNumber(
        updated.min_rr_floor,
        3
      )}, trend ${fmtNumber(updated.min_trend_strength, 6)}`
    );
    return;
  }

  setText("guard_event_detail", JSON.stringify(event).slice(0, 180));
}

function renderNews(newsPayload) {
  const list = document.getElementById("news_list");
  const sourceSelect = document.getElementById("news_source");
  if (!list) return;

  latestNewsPayload = newsPayload || latestNewsPayload;
  setText("news_updated", `News update: ${fmtTime(newsPayload.generated_at)}`);
  const rawItems = Array.isArray(newsPayload.items) ? newsPayload.items : [];
  const errors = Array.isArray(newsPayload.errors) ? newsPayload.errors : [];
  const sourceSet = new Set(["ALL"]);
  rawItems.forEach((item) => sourceSet.add(String(item.source || "Unknown")));

  if (sourceSelect) {
    const current = sourceSelect.value || "ALL";
    sourceSelect.innerHTML = Array.from(sourceSet)
      .map((source) => `<option value="${escapeHtml(source)}">${escapeHtml(source)}</option>`)
      .join("");
    sourceSelect.value = sourceSet.has(current) ? current : "ALL";
    newsSourceFilter = sourceSelect.value;
  }

  const search = normalizeText(newsSearchFilter);
  const sourceFilter = String(newsSourceFilter || "ALL");
  const items = rawItems.filter((item) => {
    if (sourceFilter !== "ALL" && String(item.source || "Unknown") !== sourceFilter) return false;
    if (!search) return true;
    const hay = `${item.title || ""} ${item.source || ""}`.toLowerCase();
    return hay.includes(search);
  });

  if (!items.length) {
    list.innerHTML = "<li class=\"news-item\">No news matches the current filters.</li>";
  } else {
    list.innerHTML = items
      .map((item) => {
        const title = escapeHtml(item.title || "(untitled)");
        const source = escapeHtml(item.source || "Unknown");
        const published = escapeHtml(fmtTime(item.published_at));
        const link = item.link ? escapeHtml(item.link) : "";
        const linkedTitle = link
          ? `<a href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>`
          : `<span>${title}</span>`;
        return `<li class="news-item">
          ${linkedTitle}
          <div class="news-meta">
            <span class="news-source">${source}</span>
            <span>${published}</span>
          </div>
        </li>`;
      })
      .join("");
  }

  if (errors.length) {
    setNewsStatus(`Some sources failed (${errors.length}). Using available feeds.`, true);
  } else {
    setNewsStatus(`Loaded ${items.length} headlines from configured sources.`);
  }
}

function setCoinSelectOptions(symbols, selectedSymbol) {
  const select = document.getElementById("coin_select");
  if (!select) return;

  availableCoins = ["ALL", ...symbols];
  select.innerHTML = "";

  availableCoins.forEach((symbol) => {
    const option = document.createElement("option");
    option.value = symbol;
    option.textContent = symbol;
    select.appendChild(option);
  });

  const effectiveSelected = selectedSymbol && symbols.includes(selectedSymbol) ? selectedSymbol : "ALL";
  selectedCoin = effectiveSelected;
  select.value = effectiveSelected;
}

function renderWatchlistChips() {
  const el = document.getElementById("watchlist_chips");
  if (!el) return;
  if (!watchlistSymbols.length) {
    el.innerHTML = '<span class="control-hint">No symbols selected.</span>';
    return;
  }
  el.innerHTML = watchlistSymbols
    .map(
      (symbol) =>
        `<span class="chip">${escapeHtml(symbol)}<button type="button" data-remove-symbol="${escapeHtml(
          symbol
        )}" title="Remove">x</button></span>`
    )
    .join("");
}

function renderSymbolsDatalist(symbols) {
  const datalist = document.getElementById("symbols_datalist");
  if (!datalist) return;
  datalist.innerHTML = symbols
    .slice(0, 1500)
    .map((symbol) => `<option value="${escapeHtml(symbol)}"></option>`)
    .join("");
}

async function loadSymbolCatalog(query = "", limit = 800) {
  const qs = new URLSearchParams();
  if (query) qs.set("q", query);
  qs.set("limit", String(limit));
  const response = await fetch(`/api/symbols?${qs.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  allCatalogSymbols = Array.isArray(payload.symbols) ? payload.symbols : [];
  renderSymbolsDatalist(allCatalogSymbols);
}

function addWatchlistSymbol(rawSymbol) {
  const symbol = normalizeSymbol(rawSymbol);
  if (!symbol) return false;
  if (allCatalogSymbols.length && !allCatalogSymbols.includes(symbol)) {
    setCoinStatus(`${symbol} is not in current Binance futures symbol catalog.`, true);
    return false;
  }
  if (watchlistSymbols.includes(symbol)) {
    return true;
  }
  watchlistSymbols.push(symbol);
  renderWatchlistChips();
  return true;
}

async function loadCoinOptions() {
  const response = await fetch("/api/options", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const data = await response.json();
  const symbols = Array.isArray(data.symbols) ? data.symbols : [];
  setCoinSelectOptions(symbols, data.selected_symbol);
  watchlistSymbols = Array.isArray(data.selected_symbols) ? data.selected_symbols.map(normalizeSymbol) : [];
  renderWatchlistChips();
}

async function saveSelectedCoin() {
  const select = document.getElementById("coin_select");
  if (!select) return;

  const symbol = select.value;
  selectedCoin = symbol;

  if (symbol === "ALL") {
    setCoinStatus("Display filter set to ALL. Select a specific coin to update live trading runtime.");
    return;
  }

  const response = await fetch("/api/config/symbol", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol }),
  });

  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }

  watchlistSymbols = [symbol];
  renderWatchlistChips();
  setCoinStatus(payload.message || `${symbol} saved and applied to runtime.`);
}

async function saveWatchlist() {
  if (!watchlistSymbols.length) {
    throw new Error("Watchlist is empty");
  }
  const response = await fetch("/api/config/symbols", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbols: watchlistSymbols }),
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  setCoinStatus(payload.message || `Saved ${watchlistSymbols.length} symbols and applied to runtime.`);
}

async function refreshTradeNow() {
  await Promise.all([tickState(), tickHistory()]);
  setCoinStatus("Trade data refreshed.");
}

function bindCoinControls() {
  const select = document.getElementById("coin_select");
  const saveBtn = document.getElementById("save_coin_btn");
  const searchInput = document.getElementById("coin_search");
  const addBtn = document.getElementById("add_coin_btn");
  const saveWatchlistBtn = document.getElementById("save_watchlist_btn");
  const refreshTradeBtn = document.getElementById("refresh_trade_btn");
  const chipsWrap = document.getElementById("watchlist_chips");
  if (!select || !saveBtn || !searchInput || !addBtn || !saveWatchlistBtn || !refreshTradeBtn || !chipsWrap) return;

  select.addEventListener("change", () => {
    selectedCoin = select.value;
    if (latestStatePayload) {
      renderState(latestStatePayload);
    } else {
      renderHistoryRows(latestHistoryPayload);
    }
  });

  saveBtn.addEventListener("click", async () => {
    try {
      await saveSelectedCoin();
    } catch (error) {
      setCoinStatus(`Save failed: ${error.message}`, true);
    }
  });

  searchInput.addEventListener("input", async () => {
    const q = normalizeSymbol(searchInput.value);
    if (!q || q.length < 2) return;
    try {
      await loadSymbolCatalog(q, 200);
    } catch {
      // Keep last good catalog results in UI.
    }
  });

  searchInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const ok = addWatchlistSymbol(searchInput.value);
    if (ok) {
      setCoinStatus(`Added ${normalizeSymbol(searchInput.value)} to watchlist.`);
      searchInput.value = "";
    }
  });

  addBtn.addEventListener("click", () => {
    const ok = addWatchlistSymbol(searchInput.value);
    if (!ok) return;
    setCoinStatus(`Added ${normalizeSymbol(searchInput.value)} to watchlist.`);
    searchInput.value = "";
  });

  chipsWrap.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const removeSymbol = target.getAttribute("data-remove-symbol");
    if (!removeSymbol) return;
    watchlistSymbols = watchlistSymbols.filter((symbol) => symbol !== removeSymbol);
    renderWatchlistChips();
  });

  saveWatchlistBtn.addEventListener("click", async () => {
    try {
      await saveWatchlist();
    } catch (error) {
      setCoinStatus(`Save failed: ${error.message}`, true);
    }
  });

  refreshTradeBtn.addEventListener("click", async () => {
    try {
      await refreshTradeNow();
    } catch (error) {
      setCoinStatus(`Refresh failed: ${error.message}`, true);
    }
  });
}

function bindOpportunityControls() {
  const bucketSelect = document.getElementById("opportunity_bucket_filter");
  if (!bucketSelect) return;
  bucketSelect.addEventListener("change", () => {
    selectedBucketFilter = bucketSelect.value || "ALL";
  });
}

function bindNewsControls() {
  const btn = document.getElementById("refresh_news_btn");
  const searchInput = document.getElementById("news_search");
  const sourceSelect = document.getElementById("news_source");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    try {
      await tickNews(true);
    } catch (error) {
      setNewsStatus(`News refresh failed: ${error.message}`, true);
    }
  });

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      newsSearchFilter = searchInput.value;
      renderNews(latestNewsPayload);
    });
  }

  if (sourceSelect) {
    sourceSelect.addEventListener("change", () => {
      newsSourceFilter = sourceSelect.value;
      renderNews(latestNewsPayload);
    });
  }
}

function bindSystemLogControls() {
  const refreshBtn = document.getElementById("refresh_logs_btn");
  if (!refreshBtn) return;
  refreshBtn.addEventListener("click", async () => {
    try {
      await tickState();
      setText("system_log_meta", "Logs refreshed.");
    } catch (error) {
      setText("system_log_meta", `Log refresh failed: ${error.message}`);
    }
  });
}

async function tickState() {
  const dot = document.getElementById("live_dot");
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    renderState(state);
    if (dot) { dot.classList.add("live"); dot.classList.remove("error"); }
  } catch (error) {
    setText("connection", `Disconnected: ${error.message}`);
    if (dot) { dot.classList.remove("live"); dot.classList.add("error"); }
  }
}

async function tickNews(force = false) {
  const suffix = force ? "?force=1" : "";
  const response = await fetch(`/api/news${suffix}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  renderNews(payload);
}

async function tickHistory() {
  try {
    const response = await fetch("/api/history?limit=500", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    latestHistoryPayload = payload;
    renderHistoryRows(payload);
  } catch (error) {
    setText("history_meta", `History unavailable: ${error.message}`);
  }
}

// --- Analytics Charts ---
let equityChart = null;
let winrateChart = null;
let pnlDistChart = null;
let drawdownChart = null;
let latestAnalytics = null;

const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
  },
  scales: {
    x: {
      ticks: { color: "#9db2ce", font: { size: 10 }, maxTicksLimit: 8 },
      grid: { color: "rgba(112,145,194,0.12)" },
    },
    y: {
      ticks: { color: "#9db2ce", font: { size: 10 } },
      grid: { color: "rgba(112,145,194,0.12)" },
    },
  },
};

function fmtChartTime(val) {
  if (!val) return "";
  const d = typeof val === "number" ? new Date(val) : new Date(val);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function initCharts() {
  if (typeof Chart === "undefined") return;

  const eqCtx = document.getElementById("equity_chart");
  if (eqCtx) {
    equityChart = new Chart(eqCtx, {
      type: "line",
      data: { labels: [], datasets: [{ data: [], borderColor: "#42d2ff", backgroundColor: "rgba(66,210,255,0.08)", fill: true, tension: 0.3, pointRadius: 2 }] },
      options: { ...chartDefaults, plugins: { ...chartDefaults.plugins, tooltip: { callbacks: { label: (ctx) => `$${ctx.parsed.y.toFixed(4)}` } } } },
    });
  }

  const wrCtx = document.getElementById("winrate_chart");
  if (wrCtx) {
    winrateChart = new Chart(wrCtx, {
      type: "line",
      data: { labels: [], datasets: [{ data: [], borderColor: "#5dffb8", backgroundColor: "rgba(93,255,184,0.08)", fill: true, tension: 0.3, pointRadius: 2 }] },
      options: {
        ...chartDefaults,
        scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, min: 0, max: 1, ticks: { ...chartDefaults.scales.y.ticks, callback: (v) => `${(v * 100).toFixed(0)}%` } } },
        plugins: { ...chartDefaults.plugins, tooltip: { callbacks: { label: (ctx) => `${(ctx.parsed.y * 100).toFixed(1)}%` } } },
      },
    });
  }

  const pnlCtx = document.getElementById("pnl_dist_chart");
  if (pnlCtx) {
    pnlDistChart = new Chart(pnlCtx, {
      type: "bar",
      data: {
        labels: [],
        datasets: [{
          data: [],
          backgroundColor: ["#ff6e63", "#ff9387", "#ffcf73", "#5dffb8", "#42d2ff", "#1fc881"],
          borderRadius: 4,
        }],
      },
      options: chartDefaults,
    });
  }

  const ddCtx = document.getElementById("drawdown_chart");
  if (ddCtx) {
    drawdownChart = new Chart(ddCtx, {
      type: "line",
      data: { labels: [], datasets: [{ data: [], borderColor: "#ff6e63", backgroundColor: "rgba(255,110,99,0.12)", fill: true, tension: 0.3, pointRadius: 1 }] },
      options: { ...chartDefaults, plugins: { ...chartDefaults.plugins, tooltip: { callbacks: { label: (ctx) => `-$${ctx.parsed.y.toFixed(4)}` } } } },
    });
  }
}

function renderAnalytics(data) {
  latestAnalytics = data;
  if (!data || !data.total_trades) return;

  const s = data.summary || {};
  setText("analytics_total_trades", data.total_trades);
  setText("analytics_win_rate", fmtPercent(s.win_rate));
  setText("analytics_profit_factor", fmtNumber(data.profit_factor, 2));
  setText("analytics_expectancy", fmtNumber(s.expectancy_r, 4));

  const pnlEl = document.getElementById("analytics_total_pnl");
  if (pnlEl) {
    const pnl = s.total_pnl_usd ?? 0;
    pnlEl.textContent = `$${Number(pnl).toFixed(4)}`;
    pnlEl.classList.remove("positive", "negative");
    pnlEl.classList.add(pnl >= 0 ? "positive" : "negative");
  }

  const ddEl = document.getElementById("analytics_max_dd");
  if (ddEl) {
    ddEl.textContent = `$${Number(data.drawdown?.max_drawdown_usd ?? 0).toFixed(4)}`;
    ddEl.classList.add("negative");
  }

  setText("analytics_best_streak", `${data.streaks?.max_win_streak ?? 0}W`);
  setText("analytics_worst_streak", `${data.streaks?.max_loss_streak ?? 0}L`);

  // Sync profit factor to performance card
  const pfEl = document.getElementById("perf_profit_factor");
  if (pfEl) pfEl.textContent = fmtNumber(data.profit_factor, 2);

  // Update charts
  if (equityChart && data.equity_curve?.length) {
    const labels = data.equity_curve.map((p) => fmtChartTime(p.time));
    const values = data.equity_curve.map((p) => p.equity);
    equityChart.data.labels = labels;
    equityChart.data.datasets[0].data = values;
    equityChart.update("none");
  }

  if (winrateChart && data.rolling_win_rate?.length) {
    const labels = data.rolling_win_rate.map((p) => `#${p.trade_num}`);
    const values = data.rolling_win_rate.map((p) => p.win_rate);
    winrateChart.data.labels = labels;
    winrateChart.data.datasets[0].data = values;
    winrateChart.update("none");
  }

  if (pnlDistChart && data.pnl_distribution) {
    const labels = Object.keys(data.pnl_distribution);
    const values = Object.values(data.pnl_distribution);
    pnlDistChart.data.labels = labels;
    pnlDistChart.data.datasets[0].data = values;
    pnlDistChart.update("none");
  }

  if (drawdownChart && data.drawdown?.curve?.length) {
    const labels = data.drawdown.curve.map((p) => fmtChartTime(p.time));
    const values = data.drawdown.curve.map((p) => p.drawdown);
    drawdownChart.data.labels = labels;
    drawdownChart.data.datasets[0].data = values;
    drawdownChart.update("none");
  }

  // Symbol performance grid
  renderSymbolPerformance(data.symbol_breakdown || []);
}

function renderSymbolPerformance(symbols) {
  const grid = document.getElementById("symbol_performance_grid");
  if (!grid) return;

  if (!symbols.length) {
    grid.innerHTML = '<p class="meta-inline">No symbol data available.</p>';
    return;
  }

  grid.innerHTML = symbols
    .map((s) => {
      const cls = s.pnl_usd >= 0 ? "profitable" : "losing";
      return `<div class="symbol-card ${cls}">
        <span class="symbol-name">${escapeHtml(s.symbol)}</span>
        <div class="symbol-stats">
          <span>Trades</span><strong>${s.trades}</strong>
          <span>Win Rate</span><strong>${fmtPercent(s.win_rate)}</strong>
          <span>PnL (R)</span><strong>${fmtNumber(s.pnl_r, 3)}</strong>
          <span>PnL ($)</span><strong>${fmtNumber(s.pnl_usd, 4)}</strong>
        </div>
      </div>`;
    })
    .join("");
}

async function tickAnalytics() {
  try {
    const response = await fetch("/api/analytics", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderAnalytics(data);
  } catch (error) {
    // Analytics fetch failed silently - non-critical
  }
}

function initSectionNav() {
  const tabs = document.querySelectorAll(".section-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = document.getElementById(tab.dataset.target);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
    });
  });

  const sectionIds = ["sect-overview", "sect-analytics", "sect-opportunities", "sect-market", "sect-activity", "sect-history"];
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          tabs.forEach((t) => t.classList.toggle("active", t.dataset.target === id));
        }
      });
    },
    { rootMargin: "-10% 0px -70% 0px", threshold: 0 }
  );
  sectionIds.forEach((id) => {
    const el = document.getElementById(id);
    if (el) observer.observe(el);
  });
}

function initCollapsibles() {
  document.querySelectorAll(".collapse-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const section = btn.closest(".collapsible-section");
      if (!section) return;
      const isCollapsed = section.classList.toggle("collapsed");
      btn.textContent = isCollapsed ? "▸" : "▾";
    });
  });
}

async function init() {
  bindCoinControls();
  bindOpportunityControls();
  bindNewsControls();
  bindSystemLogControls();
  initSectionNav();
  initCollapsibles();

  try {
    await loadCoinOptions();
    await loadSymbolCatalog("", 1200);
    setCoinStatus("Coin options loaded. Add any symbol and save watchlist to apply live.");
  } catch (error) {
    setCoinStatus(`Failed to load coin options: ${error.message}`, true);
  }

  try {
    await tickNews(true);
  } catch (error) {
    setNewsStatus(`Failed to load news: ${error.message}`, true);
  }

  initCharts();

  setInterval(tickState, REFRESH_MS);
  setInterval(tickNews, NEWS_REFRESH_MS);
  setInterval(tickHistory, HISTORY_REFRESH_MS);
  setInterval(tickAnalytics, ANALYTICS_REFRESH_MS);
  tickState();
  tickHistory();
  tickAnalytics();
}

init();
