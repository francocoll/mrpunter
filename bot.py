import asyncio
import html
import logging
import re
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

import config
import storage
from api import (
    search_leagues, get_female_leagues, get_events_for_leagues, Match,
    get_football_countries, get_leagues_by_country, search_match, _is_female,
)


def _is_female_match(m: Match) -> bool:
    return _is_female(m)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

H = html.escape  # shorthand


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M UTC")
    except Exception:
        return iso


def _fmt_match(m: Match) -> str:
    if m.is_live:
        mins = m.game_time // 60
        status = f"🔴 EN VIVO {mins}'"
    else:
        status = f"🗓 {_fmt_date(m.start_time)}"
    line = f"  {status}\n  {H(m.home)} vs {H(m.away)}"
    if m.odds_home and m.odds_draw and m.odds_away:
        line += f"\n  <code>{m.odds_home} x {m.odds_draw} x {m.odds_away}</code>"
    elif m.hc_home and m.hc_away and m.hc_value is not None:
        hc = f"{m.hc_value:+g}" if m.hc_value != 0 else "0"
        line += f"\n  <code>HC {hc}: {m.hc_home} x {m.hc_away}</code>"
    return line


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def _cache_leagues(ctx: ContextTypes.DEFAULT_TYPE, leagues) -> None:
    """Store league info in bot_data so callbacks can look it up by ID."""
    if "league_cache" not in ctx.application.bot_data:
        ctx.application.bot_data["league_cache"] = {}
    for lg in leagues:
        ctx.application.bot_data["league_cache"][lg.league_id] = {
            "name": lg.name,
            "country": lg.country,
        }


def _lookup_league(ctx: ContextTypes.DEFAULT_TYPE, league_id: str) -> dict:
    cache = ctx.application.bot_data.get("league_cache", {})
    return cache.get(league_id, {"name": league_id, "country": ""})


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Bot de Fútbol ⚽</b>\n\n"
        "Comandos disponibles:\n"
        "/paises — Ver todos los países con sus IDs\n"
        "/pais <code>&lt;id&gt;</code> — Ver ligas de un país\n"
        "/buscar <code>&lt;nombre&gt;</code> — Buscar ligas por nombre o país\n"
        "/agregar femeninas — Agregar todas las ligas femeninas de una\n"
        "/agregar <code>&lt;id&gt;</code> — Agregar liga por ID\n"
        "/ligas — Ver tus ligas favoritas\n"
        "/partidos — Ver partidos de tus ligas favoritas\n"
        "/liga <code>&lt;id&gt;</code> — Ver partidos de una liga específica\n"
        "/seguir <code>Local - Visitante</code> — Seguir un partido (o pegar lista con tabulaciones)\n"
        "/vigilados — Ver partidos en seguimiento\n"
        "/monitorear — Activar notificaciones automáticas\n"
        "/pausar — Detener notificaciones\n"
        "/quitar <code>&lt;id&gt;</code> — Quitar una liga de favoritos\n\n"
        "El bot te notificará cuando aparezca un partido nuevo en tus ligas favoritas."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_buscar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Uso: /buscar &lt;nombre de liga o país&gt;", parse_mode=ParseMode.HTML)
        return

    query = " ".join(ctx.args)
    msg = await update.message.reply_text(
        f"🔍 Buscando <b>{H(query)}</b>...", parse_mode=ParseMode.HTML
    )

    try:
        results = await search_leagues(query)
    except Exception as e:
        logger.error("Error buscando ligas: %s", e)
        await msg.edit_text("❌ Error al consultar la API.")
        return

    if not results:
        await msg.edit_text(
            f"No se encontraron ligas para <b>{H(query)}</b>.", parse_mode=ParseMode.HTML
        )
        return

    results = results[:15]
    _cache_leagues(ctx, results)
    favs = storage.load_favorites()

    keyboard = []
    lines = [f'<b>Resultados para "{H(query)}":</b>\n']
    for lg in results:
        already = "✅ " if lg.league_id in favs else ""
        lines.append(
            f"<code>{lg.league_id}</code>\n"
            f"{already}{H(lg.country)} — {H(lg.name)} ({lg.events_qty} eventos)"
        )
        row = []
        if lg.league_id not in favs:
            row.append(InlineKeyboardButton(
                f"➕ Agregar",
                callback_data=f"add|{lg.league_id}",
            ))
        row.append(InlineKeyboardButton(
            f"📋 Partidos",
            callback_data=f"matches|{lg.league_id}",
        ))
        keyboard.append(row)

    await msg.edit_text(
        "\n\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def cmd_paises(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("⏳ Cargando países...")
    try:
        countries = await get_football_countries()
    except Exception as e:
        logger.error("cmd_paises error: %s", e)
        await msg.edit_text("❌ Error al consultar la API.")
        return

    countries.sort(key=lambda c: c.name)
    lines = ["<b>Países disponibles en Fútbol:</b>\n"]
    for c in countries:
        lines.append(f"<code>{c.country_id}</code> — {H(c.name)} ({c.events_qty} eventos)")

    for chunk in _split_message("\n".join(lines)):
        await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
    await msg.delete()


async def cmd_pais(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text(
            "Uso: /pais <code>&lt;id&gt;</code>\n"
            "Obtené los IDs con /paises.",
            parse_mode=ParseMode.HTML,
        )
        return

    country_id = ctx.args[0].strip()
    msg = await update.message.reply_text("⏳ Cargando ligas...")

    try:
        country, leagues = await get_leagues_by_country(country_id)
    except Exception as e:
        logger.error("cmd_pais error: %s", e)
        await msg.edit_text("❌ Error al consultar la API.")
        return

    if country is None:
        await msg.edit_text(f"No se encontró el país con ID <code>{H(country_id)}</code>.", parse_mode=ParseMode.HTML)
        return

    favs = storage.load_favorites()
    keyboard = []
    lines = [f"<b>🌍 {H(country.name)} — Ligas disponibles:</b>\n"]
    for lg in leagues:
        already = "✅ " if lg.league_id in favs else ""
        lines.append(
            f"{already}<code>{lg.league_id}</code>\n"
            f"  {H(lg.name)} ({lg.events_qty} eventos)"
        )
        row = []
        if lg.league_id not in favs:
            row.append(InlineKeyboardButton("➕ Agregar", callback_data=f"add|{lg.league_id}"))
        row.append(InlineKeyboardButton("📋 Partidos", callback_data=f"matches|{lg.league_id}"))
        keyboard.append(row)
        _cache_leagues(ctx, [lg])

    full_text = "\n".join(lines)
    chunks = _split_message(full_text)
    await msg.edit_text(
        chunks[0],
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )
    for chunk in chunks[1:]:
        await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def cmd_agregar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /agregar femeninas        → agrega todas las ligas femeninas
    /agregar <id> [id2 ...]   → agrega una o varias ligas por ID
    """
    if not ctx.args:
        await update.message.reply_text(
            "Uso:\n"
            "  /agregar femeninas — agrega todas las ligas femeninas\n"
            "  /agregar &lt;id&gt; [id2 ...] — agrega por ID",
            parse_mode=ParseMode.HTML,
        )
        return

    if ctx.args[0].lower() == "femeninas":
        msg = await update.message.reply_text("⏳ Buscando ligas femeninas...")
        try:
            leagues = await get_female_leagues()
        except Exception as e:
            logger.error("Error get_female_leagues: %s", e)
            await msg.edit_text("❌ Error al consultar la API.")
            return

        added, skipped = [], []
        for lg in leagues:
            if storage.add_favorite(lg.league_id, lg.name, lg.country):
                added.append(lg)
            else:
                skipped.append(lg)

        lines = [f"<b>Ligas femeninas agregadas ({len(added)}):</b>"]
        for lg in added:
            lines.append(f"  ✅ {H(lg.country)} — {H(lg.name)}")
        if skipped:
            lines.append(f"\n<i>Ya estaban en favoritos: {len(skipped)}</i>")

        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    # Add by IDs
    all_leagues = None
    added, not_found = [], []
    for lid in ctx.args:
        lid = lid.strip()
        info = _lookup_league(ctx, lid)
        if info["name"] != lid:
            # found in cache
            storage.add_favorite(lid, info["name"], info["country"])
            added.append(f"{H(info['country'])} — {H(info['name'])}")
        else:
            # not in cache, try fetching from API
            if all_leagues is None:
                try:
                    from api import get_football_leagues
                    raw = await get_football_leagues()
                    all_leagues = {lg.league_id: lg for lg in raw}
                except Exception:
                    all_leagues = {}
            lg = all_leagues.get(lid)
            if lg:
                storage.add_favorite(lg.league_id, lg.name, lg.country)
                added.append(f"{H(lg.country)} — {H(lg.name)}")
            else:
                # Liga fuera de temporada: guardar igual con nombre pendiente
                storage.add_favorite(lid, f"Liga {lid}", "")
                added.append(f"<i>(sin temporada activa)</i> — <code>{lid}</code>")

    lines = []
    if added:
        lines.append(f"<b>Agregadas ({len(added)}):</b>")
        lines += [f"  ✅ {a}" for a in added]
    if not_found:
        lines.append(f"\n<b>No encontradas:</b>")
        lines += [f"  ❌ <code>{H(i)}</code>" for i in not_found]

    await update.message.reply_text("\n".join(lines) or "Sin cambios.", parse_mode=ParseMode.HTML)


async def cmd_ligas(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    favs = storage.load_favorites()
    if not favs:
        await update.message.reply_text(
            "No tenés ligas favoritas aún.\nUsá /buscar para agregar."
        )
        return

    lines = [f"<b>Tus ligas favoritas ({len(favs)}):</b>\n"]
    keyboard = []
    for lid, info in favs.items():
        lines.append(
            f"🏆 {H(info['country'])} — {H(info['name'])}\n"
            f"<code>{lid}</code>"
        )
        keyboard.append([
            InlineKeyboardButton(
                f"❌ {info['name'][:40]}",
                callback_data=f"remove|{lid}",
            )
        ])

    full_text = "\n\n".join(lines)
    try:
        chunks = _split_message(full_text)
        for i, chunk in enumerate(chunks):
            # Only attach the remove-buttons keyboard to the last chunk
            markup = InlineKeyboardMarkup(keyboard) if i == len(chunks) - 1 else None
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as e:
        logger.error("cmd_ligas error: %s", e)
        await update.message.reply_text("❌ Error al mostrar las ligas.")


async def cmd_liga(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /liga <id>  → muestra los partidos de esa liga
    """
    if not ctx.args:
        await update.message.reply_text(
            "Uso: /liga <code>&lt;id&gt;</code>\n"
            "Encontrá el ID con /buscar.",
            parse_mode=ParseMode.HTML,
        )
        return

    lid = ctx.args[0].strip()
    msg = await update.message.reply_text("⏳ Consultando partidos...")

    try:
        matches = await get_events_for_leagues({lid})
    except Exception as e:
        logger.error("Error get_events_for_leagues: %s", e)
        await msg.edit_text("❌ Error al consultar la API.")
        return

    if not matches:
        await msg.edit_text("No hay partidos disponibles para esa liga.")
        return

    matches.sort(key=lambda m: (not m.is_live, m.start_time))
    league_name = matches[0].league_name

    lines = [f"🏆 <b>{H(league_name)}</b>\n"]
    for m in matches:
        lines.append(_fmt_match(m))

    full_text = "\n\n".join(lines)
    chunks = _split_message(full_text)
    await msg.edit_text(chunks[0], parse_mode=ParseMode.HTML)
    for chunk in chunks[1:]:
        await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def cmd_quitar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Uso: /quitar &lt;league_id&gt;", parse_mode=ParseMode.HTML)
        return
    lid = ctx.args[0].strip()
    removed = storage.remove_favorite(lid)
    if removed:
        await update.message.reply_text(
            f"✅ Liga <code>{H(lid)}</code> quitada de favoritos.", parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"⚠️ La liga <code>{H(lid)}</code> no estaba en favoritos.", parse_mode=ParseMode.HTML
        )


async def cmd_partidos(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    favs = storage.load_favorites()
    if not favs:
        await update.message.reply_text(
            "No tenés ligas favoritas. Usá /buscar para agregar."
        )
        return

    msg = await update.message.reply_text("⏳ Consultando partidos...")

    try:
        matches = await get_events_for_leagues(set(favs.keys()))
    except Exception as e:
        logger.error("Error obteniendo partidos: %s", e)
        await msg.edit_text("❌ Error al consultar la API.")
        return

    if not matches:
        await msg.edit_text("No hay partidos disponibles en tus ligas favoritas.")
        return

    by_league: dict[str, list[Match]] = {}
    for m in matches:
        by_league.setdefault(m.league_name, []).append(m)

    for league_matches in by_league.values():
        league_matches.sort(key=lambda m: (not m.is_live, m.start_time))

    blocks = []
    for league_name, league_matches in sorted(by_league.items()):
        header = f"🏆 <b>{H(league_name)}</b>"
        match_lines = [_fmt_match(m) for m in league_matches]
        blocks.append(header + "\n" + "\n\n".join(match_lines))

    full_text = "\n\n".join(blocks)
    chunks = _split_message(full_text)
    await msg.edit_text(chunks[0], parse_mode=ParseMode.HTML)
    for chunk in chunks[1:]:
        await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


# ── Inline callbacks ──────────────────────────────────────────────────────────

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[0]

    if action == "add":
        lid = parts[1]
        info = _lookup_league(ctx, lid)
        name, country = info["name"], info["country"]
        added = storage.add_favorite(lid, name, country)
        if added:
            await query.edit_message_text(
                f"✅ <b>{H(name)}</b> agregada a favoritos.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.answer("Ya estaba en favoritos.", show_alert=True)

    elif action == "remove":
        lid = parts[1]
        favs = storage.load_favorites()
        name = favs.get(lid, {}).get("name", lid)
        storage.remove_favorite(lid)
        await query.edit_message_text(
            f"❌ <b>{H(name)}</b> quitada de favoritos.",
            parse_mode=ParseMode.HTML,
        )

    elif action == "matches":
        lid = parts[1]
        await query.answer("Buscando partidos...")
        try:
            matches = await get_events_for_leagues({lid})
        except Exception as e:
            logger.error("matches callback error: %s", e)
            await query.answer("❌ Error al consultar la API.", show_alert=True)
            return

        if not matches:
            await query.answer("No hay partidos disponibles.", show_alert=True)
            return

        matches.sort(key=lambda m: (not m.is_live, m.start_time))
        league_name = matches[0].league_name
        lines = [f"🏆 <b>{H(league_name)}</b>\n"]
        for m in matches:
            lines.append(_fmt_match(m))

        full_text = "\n\n".join(lines)
        chunks = _split_message(full_text)
        await query.message.reply_text(chunks[0], parse_mode=ParseMode.HTML)
        for chunk in chunks[1:]:
            await query.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    elif action == "watch_pick":
        # watch_pick|home|away|gender|event_id
        _, home_q, away_q, gender, event_id = parts
        gender_val = gender if gender in ("F", "M") else None
        wid = storage.add_watch(home_q, away_q, gender_val)
        gender_label = f" ({'Femenino' if gender_val == 'F' else 'Masculino'})" if gender_val else ""
        await query.edit_message_text(
            f"✅ Seguimiento agregado (ID: <code>{wid}</code>)\n"
            f"<b>{H(home_q)}</b> vs <b>{H(away_q)}</b>{H(gender_label)}",
            parse_mode=ParseMode.HTML,
        )

    elif action == "rmwatch":
        wid = parts[1]
        removed = storage.remove_watch(wid)
        if removed:
            await query.edit_message_text(f"❌ Partido <code>{wid}</code> quitado del seguimiento.", parse_mode=ParseMode.HTML)
        else:
            await query.answer("Ya no estaba en la lista.", show_alert=True)


# ── Background monitor ────────────────────────────────────────────────────────

def _snapshot(m: Match) -> dict:
    return {
        "h": m.odds_home, "d": m.odds_draw, "a": m.odds_away,
        "hc_v": m.hc_value, "hc_h": m.hc_home, "hc_a": m.hc_away,
    }


_ODDS_THRESHOLD = 0.2 / 3  # ~6.67% — equivalente a un cambio de 3.00 → 3.20


def _odds_changed(initial: dict, current: dict) -> bool:
    """True si alguna cuota se movió >= umbral % desde la snapshot inicial."""
    for key in ("h", "d", "a", "hc_h", "hc_a"):
        i, c = initial.get(key), current.get(key)
        if i and c and abs(c - i) / i >= _ODDS_THRESHOLD:
            return True
    return False


def _fmt_odds_change(m: Match, initial: dict) -> str:
    if m.odds_home is not None:
        old_str = f"{initial['h']} x {initial['d']} x {initial['a']}" if initial.get("h") else "—"
        new_str = f"{m.odds_home} x {m.odds_draw} x {m.odds_away}"
    elif m.hc_home is not None:
        hc = f"{m.hc_value:+g}" if m.hc_value else "0"
        old_str = f"HC {hc}: {initial['hc_h']} x {initial['hc_a']}" if initial.get("hc_h") else "—"
        new_str = f"HC {hc}: {m.hc_home} x {m.hc_away}"
    else:
        return ""
    return f"  <code>{old_str}  →  {new_str}</code>"


async def monitor_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = ctx.job.chat_id
    favs = storage.load_favorites()
    if not favs:
        return

    try:
        matches = await get_events_for_leagues(set(favs.keys()))
    except Exception as e:
        logger.error("Monitor error: %s", e)
        return

    seen = storage.load_seen()
    odds_cache = storage.load_odds_cache()

    new_matches: list[Match] = []
    changed_matches: list[tuple[Match, dict]] = []  # (match, initial_snapshot)

    for m in matches:
        snap = _snapshot(m)
        if m.event_id not in seen:
            # Primera vez — guardar cuota inicial y actual
            new_matches.append(m)
            odds_cache[m.event_id] = {"initial": snap, "current": snap}
        else:
            entry = odds_cache.get(m.event_id, {})
            initial = entry.get("initial", snap)
            if not m.is_live and _odds_changed(initial, snap):
                changed_matches.append((m, initial))
                # Resetear initial para el próximo ciclo
                odds_cache[m.event_id] = {"initial": snap, "current": snap}
            else:
                odds_cache[m.event_id] = {"initial": initial, "current": snap}

    storage.save_odds_cache(odds_cache)

    # ── Notify new matches ────────────────────────────────────────────────────
    if new_matches:
        by_league: dict[str, list[Match]] = {}
        for m in new_matches:
            by_league.setdefault(m.league_name, []).append(m)

        blocks = ["🆕 <b>Nuevos partidos:</b>\n"]
        for league_name, lms in sorted(by_league.items()):
            header = f"🏆 <b>{H(league_name)}</b>"
            blocks.append(header + "\n" + "\n\n".join(_fmt_match(m) for m in lms))

        for chunk in _split_message("\n\n".join(blocks)):
            await ctx.bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML)

        storage.mark_seen([m.event_id for m in new_matches])
        logger.info("Notified %d new matches to chat %s", len(new_matches), chat_id)

    # ── Notify odds changes ───────────────────────────────────────────────────
    if config.ODDS_CHANGE_NOTIFICATIONS and changed_matches:
        by_league2: dict[str, list[tuple[Match, dict]]] = {}
        for m, old in changed_matches:
            by_league2.setdefault(m.league_name, []).append((m, old))

        blocks2 = ["📊 <b>Cambio de cuotas:</b>\n"]
        for league_name, items in sorted(by_league2.items()):
            header = f"🏆 <b>{H(league_name)}</b>"
            lines = []
            for m, old in items:
                status = f"🔴 {m.game_time // 60}'" if m.is_live else f"🗓 {_fmt_date(m.start_time)}"
                lines.append(
                    f"  {status}\n"
                    f"  {H(m.home)} vs {H(m.away)}\n"
                    f"{_fmt_odds_change(m, old)}"
                )
            blocks2.append(header + "\n" + "\n\n".join(lines))

        for chunk in _split_message("\n\n".join(blocks2)):
            await ctx.bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML)

        logger.info("Notified %d odds changes to chat %s", len(changed_matches), chat_id)

    # ── Check watchlist ───────────────────────────────────────────────────────
    from api import search_match as _search_match
    wl = storage.load_watchlist()
    pending = [w for w in wl if not w.get("notified")]
    if pending:
        updated = False
        for w in pending:
            try:
                found = await _search_match(w["home"], w["away"], w.get("gender"))
            except Exception:
                continue
            if found:
                m = found[0]
                w["event_id"] = m.event_id
                w["notified"] = True
                updated = True
                text = (
                    f"🔔 <b>Partido encontrado:</b>\n\n"
                    f"{_fmt_watch_match(m)}"
                )
                await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
                logger.info("Watch hit: %s vs %s -> event %s", w["home"], w["away"], m.event_id)
        if updated:
            storage.save_watchlist(wl)


# ── /monitorear ───────────────────────────────────────────────────────────────

def _schedule_monitor(job_queue, chat_id: int) -> None:
    job_name = f"monitor_{chat_id}"
    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    job_queue.run_repeating(
        monitor_job,
        interval=config.POLL_INTERVAL,
        first=10,
        chat_id=chat_id,
        name=job_name,
    )


async def cmd_monitorear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _schedule_monitor(ctx.job_queue, chat_id)
    storage.add_subscriber(chat_id)
    await update.message.reply_text(
        f"✅ Monitoreo activado permanentemente. Te avisaré cada "
        f"{config.POLL_INTERVAL // 60} minutos si hay partidos nuevos.\n\n"
        f"Usá /pausar para detenerlo."
    )


async def cmd_pausar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    job_name = f"monitor_{chat_id}"
    jobs = ctx.job_queue.get_jobs_by_name(job_name)
    if jobs:
        for job in jobs:
            job.schedule_removal()
        storage.remove_subscriber(chat_id)
        await update.message.reply_text("⏸ Monitoreo pausado. Usá /monitorear para reactivarlo.")
    else:
        await update.message.reply_text("No hay monitoreo activo. Usá /monitorear para iniciar.")


# ── Watchlist commands ────────────────────────────────────────────────────────

def _parse_seguir_input(raw: str) -> tuple[str, str, str | None]:
    """Parse 'Home - Away (F)' → (home, away, gender)."""
    gender = None
    m = re.search(r"\(([FfMm])\)\s*$", raw)
    if m:
        gender = m.group(1).upper()
        raw = raw[:m.start()].strip()
    parts = raw.split(" - ", 1)
    if len(parts) != 2:
        return raw.strip(), "", gender
    return parts[0].strip(), parts[1].strip(), gender


def _parse_bulk_line(line: str) -> tuple[str, str, str | None] | None:
    """
    Parse a bulk line with or without tab separator.
    Tab format:   'Country (F)\\tHome - Away'
    No-tab format: 'Country (F) Home - Away'  (Telegram strips tabs)
    Gender is extracted from (F)/(M) anywhere in the line.
    """
    line = line.strip()
    if not line:
        return None
    # Extract gender from anywhere in the line
    gender = None
    gm = re.search(r"\(([FfMm])\)", line)
    if gm:
        gender = gm.group(1).upper()
    # If tab present, use the part after the tab as the match
    if "\t" in line:
        _, match_part = line.split("\t", 1)
        match_part = match_part.strip()
    else:
        match_part = line
    # Split on first ' - ' to get home / away
    team_parts = match_part.split(" - ", 1)
    if len(team_parts) != 2:
        return None
    home, away = team_parts[0].strip(), team_parts[1].strip()
    if not home or not away:
        return None
    return home, away, gender


async def _cmd_seguir_bulk(update: Update, ctx: ContextTypes.DEFAULT_TYPE, lines: list[str]) -> None:
    valid: list[tuple[str, str, str | None]] = []
    skipped_lines: list[str] = []
    for line in lines:
        parsed = _parse_bulk_line(line)
        if parsed:
            valid.append(parsed)
        else:
            skipped_lines.append(line)

    if not valid:
        await update.message.reply_text(
            "❌ No se pudo parsear ninguna línea.\n"
            "Formato: <code>País (F)\tLocal - Visitante</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    msg = await update.message.reply_text(f"⏳ Buscando {len(valid)} partido(s)...")

    search_tasks = [search_match(home, away, gender) for home, away, gender in valid]
    results = await asyncio.gather(*search_tasks, return_exceptions=True)

    found_list: list[tuple[str, str, str | None, Match]] = []
    pending_list: list[tuple[str, str, str | None]] = []

    for (home, away, gender), result in zip(valid, results):
        if isinstance(result, Exception) or not result:
            storage.add_watch(home, away, gender)
            pending_list.append((home, away, gender))
        else:
            m = result[0]
            storage.add_watch(home, away, gender, event_id=m.event_id, notified=True)
            found_list.append((home, away, gender, m))

    out: list[str] = []
    if found_list:
        out.append(f"✅ <b>Encontrados ({len(found_list)}):</b>")
        for home, away, gender, m in found_list:
            g = " <i>(F)</i>" if gender == "F" else " <i>(M)</i>" if gender == "M" else ""
            out.append(
                f"  {H(m.home)} vs {H(m.away)}{g}\n"
                f"  <i>{H(m.league_name)}</i> — {_fmt_date(m.start_time)}"
            )

    if pending_list:
        out.append(f"\n👁 <b>En seguimiento — te aviso cuando aparezcan ({len(pending_list)}):</b>")
        for home, away, gender in pending_list:
            g = " (F)" if gender == "F" else " (M)" if gender == "M" else ""
            out.append(f"  {H(home)} vs {H(away)}{g}")

    if skipped_lines:
        out.append(f"\n⚠️ <b>Líneas omitidas ({len(skipped_lines)}):</b>")
        for s in skipped_lines:
            out.append(f"  <i>{H(s[:80])}</i>")

    full = "\n".join(out)
    first = True
    for chunk in _split_message(full):
        if first:
            await msg.edit_text(chunk, parse_mode=ParseMode.HTML)
            first = False
        else:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def cmd_seguir(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Single:  /seguir Trabzonspor - Giresun (F)
    Bulk:    /seguir
             País (F)\tLocal - Visitante
             País\tLocal - Visitante
             ...
    """
    full_text = update.message.text or ""
    raw = re.sub(r"^/\S+\s*", "", full_text, count=1).strip()

    if not raw:
        await update.message.reply_text(
            "Uso:\n"
            "  /seguir <code>Local - Visitante</code>\n"
            "  /seguir <code>Local - Visitante (F)</code>\n\n"
            "O pegá una lista con tabulaciones (una por línea):\n"
            "<pre>País (F)\tLocal - Visitante\nPaís\tLocal - Visitante</pre>",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [l for l in raw.splitlines() if l.strip()]

    # Bulk mode: multiple lines, or a single line with a tab separator
    if len(lines) > 1 or (len(lines) == 1 and "\t" in lines[0]):
        await _cmd_seguir_bulk(update, ctx, lines)
        return

    # Single mode
    home_q, away_q, gender = _parse_seguir_input(raw)

    if not away_q:
        await update.message.reply_text(
            "Separar equipos con <code> - </code> (espacio guion espacio).", parse_mode=ParseMode.HTML
        )
        return

    gender_label = f" <b>({'Femenino' if gender == 'F' else 'Masculino'})</b>" if gender else ""
    msg = await update.message.reply_text(
        f"🔍 Buscando <b>{H(home_q)}</b> vs <b>{H(away_q)}</b>{gender_label}...",
        parse_mode=ParseMode.HTML,
    )

    try:
        results = await search_match(home_q, away_q, gender)
    except Exception as e:
        logger.error("cmd_seguir search error: %s", e)
        await msg.edit_text("❌ Error al consultar la API.")
        return

    if not results:
        wid = storage.add_watch(home_q, away_q, gender)
        await msg.edit_text(
            f"👁 No encontrado aún, quedará en seguimiento (ID: <code>{wid}</code>).\n"
            f"Te aviso cuando aparezca: <b>{H(home_q)}</b> vs <b>{H(away_q)}</b>{gender_label}",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(results) == 1:
        m = results[0]
        wid = storage.add_watch(home_q, away_q, gender)
        text = f"✅ Partido encontrado y agregado (ID: <code>{wid}</code>)\n\n{_fmt_watch_match(m)}"
        await msg.edit_text(text, parse_mode=ParseMode.HTML)
        return

    # Multiple results — user picks
    lines_out = [f"🔍 Se encontraron <b>{len(results)}</b> partidos. ¿Cuál querés seguir?\n"]
    keyboard = []
    for i, m in enumerate(results):
        gender_tag = "👩 " if _is_female_match(m) else "👨 "
        lines_out.append(
            f"{i+1}. {gender_tag}<b>{H(m.home)} vs {H(m.away)}</b>\n"
            f"   <i>{H(m.league_name)}</i> — {_fmt_date(m.start_time)}"
        )
        keyboard.append([InlineKeyboardButton(
            f"{'👩' if _is_female_match(m) else '👨'} {m.home[:20]} vs {m.away[:20]}",
            callback_data=f"watch_pick|{home_q[:20]}|{away_q[:20]}|{'F' if _is_female_match(m) else 'M'}|{m.event_id}",
        )])

    await msg.edit_text(
        "\n\n".join(lines_out),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_vigilados(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wl = storage.load_watchlist()
    if not wl:
        await update.message.reply_text("No tenés partidos en seguimiento.\nUsá /seguir Local - Visitante.")
        return

    keyboard = []
    lines = ["<b>Partidos en seguimiento:</b>\n"]
    for w in wl:
        estado = "✅ encontrado" if w.get("event_id") else "⏳ esperando"
        lines.append(f"<code>{w['id']}</code> {estado}\n  {H(w['home'])} vs {H(w['away'])}")
        keyboard.append([InlineKeyboardButton(f"❌ Quitar {w['home'][:25]} vs {w['away'][:20]}", callback_data=f"rmwatch|{w['id']}")])

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def _fmt_watch_match(m: Match) -> str:
    status = f"🔴 EN VIVO {m.game_time // 60}'" if m.is_live else f"🗓 {_fmt_date(m.start_time)}"
    line = f"  {status}\n  {H(m.home)} vs {H(m.away)}\n  <i>{H(m.league_name)}</i>"
    if m.odds_home and m.odds_draw and m.odds_away:
        line += f"\n  <code>{m.odds_home} x {m.odds_draw} x {m.odds_away}</code>"
    elif m.hc_home and m.hc_away:
        hc = f"{m.hc_value:+g}" if m.hc_value else "0"
        line += f"\n  <code>HC {hc}: {m.hc_home} x {m.hc_away}</code>"
    return line


# ── Startup ───────────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    subs = storage.load_subscribers()
    if subs:
        logger.info("Reactivando monitoreo para %d chat(s): %s", len(subs), subs)
        for chat_id in subs:
            _schedule_monitor(app.job_queue, chat_id)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit(
            "❌ TELEGRAM_TOKEN no configurado. "
            "Creá un archivo .env con TELEGRAM_TOKEN=<tu_token>"
        )

    app = Application.builder().token(config.TELEGRAM_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("paises", cmd_paises))
    app.add_handler(CommandHandler("pais", cmd_pais))
    app.add_handler(CommandHandler("agregar", cmd_agregar))
    app.add_handler(CommandHandler("ligas", cmd_ligas))
    app.add_handler(CommandHandler("liga", cmd_liga))
    app.add_handler(CommandHandler("quitar", cmd_quitar))
    app.add_handler(CommandHandler("partidos", cmd_partidos))
    app.add_handler(CommandHandler("seguir", cmd_seguir))
    app.add_handler(CommandHandler("vigilados", cmd_vigilados))
    app.add_handler(CommandHandler("monitorear", cmd_monitorear))
    app.add_handler(CommandHandler("pausar", cmd_pausar))
    app.add_handler(CallbackQueryHandler(on_callback))

    logger.info("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
