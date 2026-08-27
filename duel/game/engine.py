from __future__ import annotations

import copy
import random
import secrets
from typing import Any

from .cards import CARD_DEFINITIONS, CARD_NAMES, CARDS, card_public

PLAYERS = ("player", "ai")
FACTION_PILES = {"royal": "royal_deck", "monster": "monster_deck"}
ACTION_EVENTS_KEY = "_action_events"
FIELD_LIMIT = 5


class GameError(ValueError):
    def __init__(self, message: str, *, code: str = "illegal_action", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _other(player: str) -> str:
    return "ai" if player == "player" else "player"


def _rng(state: dict) -> random.Random:
    return random.Random(f"{state['seed']}:{state['version']}:{len(state['log'])}")


def _make_cards() -> list[dict]:
    cards: list[dict] = []
    for definition in CARD_DEFINITIONS:
        for copy_index in range(definition.copies):
            cards.append({"uid": f"{definition.key}-{copy_index + 1}", "key": definition.key, "tapped": False})
    return cards


def _log(state: dict, message: str, tone: str = "neutral") -> None:
    next_id = max((int(entry.get("id", 0)) for entry in state["log"]), default=0) + 1
    state["log"].append({"id": next_id, "message": message, "tone": tone})
    state["log"] = state["log"][-30:]


def _masked_card(card: dict) -> dict:
    definition = CARDS[card["key"]]
    tavern_uid = f"{definition.key}-{definition.copies}"
    source = "tavern" if definition.tavern_source and card["uid"] == tavern_uid else definition.faction
    return {"uid": card["uid"], "hidden": True, "source": source}


def _ai_remember_player_card(state: dict, card: dict) -> None:
    """记录对手通过公开区域或蝙蝠确认过的玩家手牌位置。"""
    known = state["ai_memory"].setdefault("known_player_hand", [])
    if card["uid"] not in known:
        known.append(card["uid"])


def _event(
    state: dict,
    event_type: str,
    actor: str,
    message: str,
    *,
    source: str | None = None,
    card: dict | None = None,
    amount: int | None = None,
    starter: str | None = None,
    phase: str | None = None,
    field_slot: int | None = None,
    source_owner: str | None = None,
    destination: str | None = None,
    source_zone: str | None = None,
    destination_zone: str | None = None,
    destination_owner: str | None = None,
    hidden_card: dict | None = None,
    replacement_card: dict | None = None,
    revealed_cards: list[dict] | None = None,
    tapped: bool | None = None,
    title: str | None = None,
    history_group: str | None = None,
    record_history: bool | None = None,
    animate: bool = True,
    skippable: bool = True,
) -> None:
    events = state.get(ACTION_EVENTS_KEY)
    if events is None:
        return
    event: dict[str, Any] = {
        "id": len(events) + 1,
        "type": event_type,
        "actor": actor,
        "message": message,
        "skippable": skippable,
        "action_points": state.get("action_points", 0),
        "turn_number": state.get("turn_number", 1),
        "coins": copy.deepcopy(state.get("coins", {"player": 0, "ai": 0})),
    }
    if source is not None:
        event["source"] = source
    if card is not None:
        event["card"] = card_public(card)
    if amount is not None:
        event["amount"] = amount
    if starter is not None:
        event["starter"] = starter
    if phase is not None:
        event["phase"] = phase
    if field_slot is not None:
        event["field_slot"] = field_slot
    if source_owner is not None:
        event["source_owner"] = source_owner
    if destination is not None:
        event["destination"] = destination
    if source_zone is not None:
        event["source_zone"] = source_zone
    if destination_zone is not None:
        event["destination_zone"] = destination_zone
    if destination_owner is not None:
        event["destination_owner"] = destination_owner
    if hidden_card is not None:
        event["hidden_card"] = copy.deepcopy(hidden_card)
    if replacement_card is not None:
        event["replacement_card"] = card_public(replacement_card)
    if revealed_cards is not None:
        event["revealed_cards"] = [card_public(revealed_card) for revealed_card in revealed_cards]
    if tapped is not None:
        event["tapped"] = tapped
    if title is not None:
        event["title"] = title
    effective_history_group = history_group or state.get("_active_history_group")
    if effective_history_group is not None:
        event["history_group"] = effective_history_group
    if animate:
        events.append(event)
    history_types = {"draw", "play", "effect", "move", "tap", "coin", "activate", "trigger", "notice", "phase"}
    should_record_history = (
        (event_type in history_types and record_history is not False and (event_type != "phase" or record_history is True))
        or (event_type == "discard" and record_history is True)
    )
    if should_record_history:
        history = state.setdefault("battle_history", [])
        history_event = copy.deepcopy(event)
        history_event["history_id"] = int(state.get("battle_history_sequence", 0)) + 1
        state["battle_history_sequence"] = history_event["history_id"]
        history.append(history_event)


def _move_event(
    state: dict,
    actor: str,
    card: dict,
    message: str,
    *,
    source_zone: str,
    destination_zone: str,
    source_owner: str | None = None,
    destination_owner: str | None = None,
    field_slot: int | None = None,
    history_group: str | None = None,
    record_history: bool | None = None,
) -> None:
    if (
        destination_zone == "hand"
        and destination_owner == "player"
        and (source_owner == "ai" or source_zone in {
            "field", "tavern_faceup", "royal_discard", "monster_discard",
            # 通过龙蛋等效果明确检索并展示的牌库卡牌也是公开信息。
            # 普通摸牌不走 _move_event，因此不会被这里错误记为已知。
            "royal_deck", "monster_deck", "tavern_deck", "resolution"
        })
    ):
        _ai_remember_player_card(state, card)
    _event(
        state,
        "move",
        actor,
        message,
        card=card,
        hidden_card=_masked_card(card) if destination_zone == "hand" and destination_owner == "ai" else None,
        source_zone=source_zone,
        destination_zone=destination_zone,
        source_owner=source_owner,
        destination_owner=destination_owner,
        field_slot=field_slot,
        history_group=history_group,
        record_history=record_history,
    )


def _opponent_action_notice(state: dict, card: dict, message: str) -> None:
    _event(
        state,
        "notice",
        "ai",
        message,
        card=card,
        title="对方行动",
        skippable=False,
    )


def take_action_events(state: dict) -> list[dict]:
    return state.pop(ACTION_EVENTS_KEY, [])


def _gain_coin(
    state: dict,
    player: str,
    amount: int = 1,
    reason: str = "卡牌效果",
    *,
    source_card: dict | None = None,
    history_group: str | None = None,
    event_message: str | None = None,
) -> None:
    if state["status"] != "playing":
        return
    state["coins"][player] += amount
    who = "你" if player == "player" else "对手"
    message = event_message or f"{who}因{reason}获得 {amount} 枚金币"
    _log(state, message, "royal" if player == "player" else "monster")
    _event(
        state,
        "coin",
        player,
        message,
        amount=amount,
        card=source_card,
        history_group=history_group,
    )
    if state["coins"][player] >= 5:
        _finish(state, player, "获得第 5 枚金币")


def _finish(state: dict, winner: str | None, reason: str) -> None:
    state["status"] = "finished"
    state["winner"] = winner
    state["result_reason"] = reason
    state["pending"] = None
    text = "平局" if winner is None else ("你获胜" if winner == "player" else "对手获胜")
    _log(state, f"对局结束：{text}（{reason}）", "gold")


def _check_decks_finished(state: dict) -> None:
    if state["status"] != "playing":
        return
    # 抽牌区三个牌库（皇室 / 魔物 / 酒馆）全空才结束，酒馆已翻开的公开牌不计。
    if not state["royal_deck"] and not state["monster_deck"] and not state["tavern_deck"]:
        player_coins = state["coins"]["player"]
        ai_coins = state["coins"]["ai"]
        winner = "player" if player_coins > ai_coins else "ai" if ai_coins > player_coins else None
        _finish(state, winner, "皇室、魔物与酒馆牌库均已耗尽")


def _draw_card(state: dict, player: str, source: str, *, history_group: str | None = None) -> dict:
    draw_group_prefix = f"draw-{state['turn_number']}-{int(state.get('battle_history_sequence', 0)) + 1}"
    override_group = history_group
    if source == "royal":
        pile = state["royal_deck"]
    elif source == "monster":
        pile = state["monster_deck"]
    elif source.startswith("tavern:"):
        try:
            index = int(source.split(":", 1)[1])
            card = state["tavern_faceup"].pop(index)
        except (ValueError, IndexError):
            raise GameError("这张酒馆牌已不可用")
        card["_ai_revealed"] = True  # 酒馆取牌对双方都是公开信息
        state["hands"][player].append(card)
        if player == "player":
            _ai_remember_player_card(state, card)
        replacement = None
        if state["tavern_deck"]:
            replacement = state["tavern_deck"].pop()
            state["tavern_faceup"].insert(index, replacement)
        message = f"{'你' if player == 'player' else '对手'}从酒馆取得 1 张公开牌"
        _log(state, message)
        _event(
            state,
            "draw",
            player,
            message,
            source=source,
            card=card,
            hidden_card=_masked_card(card) if player == "ai" else None,
            replacement_card=replacement,
            source_zone="tavern_faceup",
            destination_zone="hand",
            destination_owner=player,
            history_group=override_group or f"{draw_group_prefix}-{card['uid']}",
        )
        _check_decks_finished(state)
        return card
    else:
        raise GameError("未知抽牌来源")
    if not pile:
        raise GameError("该牌库已经抽空")
    card = pile.pop()
    state["hands"][player].append(card)
    message = f"{'你' if player == 'player' else '对手'}从{'皇室' if source == 'royal' else '魔物'}牌库抽了 1 张牌"
    _log(state, message)
    _event(
        state,
        "draw",
        player,
        message,
        source=source,
        card=card if player == "player" else None,
        hidden_card=_masked_card(card) if player == "ai" else None,
        source_zone=f"{source}_deck",
        destination_zone="hand",
        destination_owner=player,
        history_group=override_group or f"{draw_group_prefix}-{card['uid']}",
    )
    _check_decks_finished(state)
    return card


def _draw_available(state: dict, player: str, preferred: str = "royal", *, history_group: str | None = None) -> dict | None:
    sources = [preferred, "monster" if preferred == "royal" else "royal"]
    sources += [f"tavern:{i}" for i in range(len(state["tavern_faceup"]))]
    for source in sources:
        try:
            return _draw_card(state, player, source, history_group=history_group)
        except GameError:
            continue
    return None


def _discard(state: dict, card: dict) -> None:
    faction = CARDS[card["key"]].faction
    card["tapped"] = False
    state[f"{faction}_discard"].append(card)


def _place_field(state: dict, player: str, card: dict) -> None:
    if len(state["fields"][player]) >= FIELD_LIMIT:
        raise GameError("场上区已满，不能再放置卡牌", details={"field_limit": FIELD_LIMIT})
    card["tapped"] = False
    state["fields"][player].append(card)


def _has_field_space(state: dict, player: str, required: int = 1) -> bool:
    return len(state["fields"][player]) + required <= FIELD_LIMIT


def _find_and_pop(cards: list[dict], uid: str) -> dict:
    for index, card in enumerate(cards):
        if card["uid"] == uid:
            return cards.pop(index)
    raise GameError("未找到指定卡牌")


def _same_mark(cards: list[dict]) -> bool:
    if len(cards) != 2:
        return False
    left, right = (CARDS[card["key"]] for card in cards)
    return (left.level is not None and left.level == right.level) or bool(set(left.crests).intersection(right.crests))


def _has_hero_sword_option(state: dict, player: str) -> bool:
    opponent = _other(player)
    return bool(
        state["fields"][opponent]
        and any(card["key"] == "holy_sword" and not card.get("tapped") for card in state["fields"][player])
    )


def _has_legal_target(state: dict, player: str, key: str, params: dict | None = None) -> bool:
    params = params or {}
    opponent = _other(player)
    if key == "mage":
        return not state["hands"][opponent] or _has_field_space(state, opponent)
    if key in {"hero4", "hero5", "hero_crest"}:
        if params.get("use_holy_sword"):
            return _has_hero_sword_option(state, player)
        normal_target = _has_field_space(state, opponent) and any(
            CARDS[c["key"]].faction != "royal" for c in state["hands"][opponent]
        )
        return normal_target or (not params and _has_hero_sword_option(state, player))
    if key == "goblin":
        return state["coins"][opponent] > state["coins"][player]
    if key == "dragonfire":
        return bool(state["fields"][opponent])
    if key == "bat":
        # 蝙蝠不指定单张目标；即使对手没有手牌和场上牌，也允许正常打出并结算。
        return True
    if key == "witch":
        # 女巫只需宣言牌名，不要求当前一定存在目标；没有命中时效果正常落空。
        return True
    return True


def _card_can_play(
    state: dict,
    player: str,
    card: dict,
    params: dict | None = None,
    *,
    ignore_action_points: bool = False,
) -> bool:
    definition = CARDS[card["key"]]
    if definition.kind == "trigger":
        return False
    if not _has_field_space(state, player):
        return False
    if card["key"] == "blacksmith" and (
        len(state["hands"][player]) < 3 or not _has_field_space(state, player, 2)
    ):
        return False
    if card["key"] == "skeleton" and state["monster_discard"] and not _has_field_space(state, player):
        return False
    if card["key"] == "dragon_egg":
        available = state["monster_discard"] + state["monster_deck"]
        if not any(c["key"] in {"dragonfire", "fire_dragon"} for c in available):
            return False
    if definition.kind == "attack" and not _has_legal_target(state, player, card["key"], params):
        return False
    return ignore_action_points or state["action_points"] > 0


def _monk_card_can_play(state: dict, player: str, monk_uid: str, card: dict) -> bool:
    """按僧侣结算时的手牌状态判断弃牌是否能免费打出。"""

    simulated = dict(state)
    simulated["hands"] = dict(state["hands"])
    simulated["hands"][player] = [
        item for item in state["hands"][player] if item["uid"] != monk_uid
    ] + [card]
    return _card_can_play(simulated, player, card, ignore_action_points=True)


def _ai_attack_damage(state: dict, attacker: str, attack_card: dict, effect: dict) -> int:
    """从 AI（被攻击方）视角，评估如果不用卫兵，这次攻击会造成多大损失。"""
    defender = _other(attacker)
    key = attack_card["key"]
    params = effect.get("params", {}) if effect else {}
    if key in {"hero4", "hero5", "hero_crest"}:
        if params.get("use_holy_sword"):
            target_uid = params.get("field_target_uid")
            target = next(
                (c for c in state["fields"][defender] if c["uid"] == target_uid), None
            )
            if target is None:
                return 0
            hero_level = CARDS[key].level
            target_level = CARDS[target["key"]].level
            coin_bonus = (
                55 if hero_level is not None and target_level is not None and hero_level > target_level else 0
            )
            return _ai_threat_value(state, target) + coin_bonus
        target_uid = params.get("target_uid")
        target = next(
            (c for c in state["hands"][defender] if c["uid"] == target_uid), None
        )
        if target is None:
            return 40
        return _ai_hero_target_value(attack_card, target)
    if key == "mage":
        number = int(params.get("number") or 0)
        matches = [c for c in state["hands"][defender] if CARDS[c["key"]].level == number]
        return 50 if not matches else 25
    if key == "witch":
        card_name = params.get("card_name")
        for zone in (state["hands"][defender], state["fields"][defender]):
            for card in zone:
                if CARDS[card["key"]].name == card_name:
                    return _ai_threat_value(state, card) + 45
        return 0
    if key == "goblin":
        if state["coins"][defender] > state["coins"][attacker]:
            return 100
        return 0
    if key == "dragonfire":
        target_uid = params.get("target_uid")
        target = next(
            (c for c in state["fields"][defender] if c["uid"] == target_uid), None
        )
        if target is None:
            return 0
        base = _ai_threat_value(state, target)
        return base + (60 if CARDS[target["key"]].level is not None else 25)
    if key == "bat":
        # 蝙蝠会看光手牌并弹回场上；等价于 _ai_bat_gain 从对方视角。
        field = state["fields"][defender]
        return sum(_ai_threat_value(state, card) for card in field) // 2 + 15
    return 30


def _ai_should_use_guard(state: dict, attacker: str, attack_card: dict, effect: dict) -> bool:
    """AI 是否应弃卫兵抵消。收益 = 阻止的损失 + 卫兵抵消后抽 1 张牌；
    成本 = 弃掉卫兵的机会成本（未来还能被再触发一次）。"""
    # 勇者攻击且不会从 AI 手牌得分时，AI 不亏金币、只损失一张手牌，不值得费一张卫兵。
    if attacker == "player" and attack_card["key"] in {"hero4", "hero5", "hero_crest"}:
        params = effect.get("params", {}) if effect else {}
        if not params.get("use_holy_sword"):
            target_uid = params.get("target_uid")
            target = next(
                (c for c in state["hands"]["ai"] if c["uid"] == target_uid), None
            )
            hero_def = CARDS[attack_card["key"]]
            if target is not None:
                target_def = CARDS[target["key"]]
                earns_coin = (
                    hero_def.level is not None
                    and target_def.level is not None
                    and hero_def.level > target_def.level
                ) or (
                    attack_card["key"] == "hero_crest"
                    and (target_def.level is not None or "monster" in target_def.crests)
                )
                if not earns_coin:
                    return False
    damage = _ai_attack_damage(state, attacker, attack_card, effect)
    # 抵消收益 ≈ 阻止损失 + refund 行动点（如果对方还有更多牌可打，价值有限）+ 抽 1
    # 卫兵机会成本：即便没有下一次攻击，也占手位，价值 ~40
    guard_reserve_value = 40
    # 己方场上有高价值持续牌时，卫兵护本身升值
    protected = sum(
        _ai_threat_value(state, card)
        for card in state["fields"]["ai"]
        if CARDS[card["key"]].persistent
    )
    guard_reserve_value += protected // 3
    # coin 差异：如果本次攻击可能直接让对手到 5 金，必须抵消
    if attacker == "player":
        gains_coin = attack_card["key"] in {"goblin"} or (
            attack_card["key"] == "mage" and damage >= 45
        ) or (
            attack_card["key"] in {"hero4", "hero5", "hero_crest", "dragonfire"} and damage >= 100
        )
        if gains_coin and state["coins"]["player"] == 4:
            return True
    return damage >= guard_reserve_value


def _trigger_guard(state: dict, attacker: str, attack_card: dict, effect: dict) -> bool:
    defender = _other(attacker)
    guards = [c for c in state["hands"][defender] if c["key"] == "guard"]
    if not guards or not _has_field_space(state, attacker):
        return False
    if defender == "ai":
        if not _ai_should_use_guard(state, attacker, attack_card, effect):
            return False
        guard = _find_and_pop(state["hands"][defender], guards[0]["uid"])
        message = "对手使用卫兵，使你的攻击无效"
        _log(state, message, "monster")
        _event(state, "trigger", defender, message, card=guard)
        _discard(state, guard)
        guard_destination = f"{CARDS[guard['key']].faction}_discard"
        _event(
            state,
            "discard",
            defender,
            "对手将“卫兵”置入弃牌区",
            card=guard,
            source_owner=defender,
            destination=guard_destination,
            source_zone="hand",
            destination_zone=guard_destination,
        )
        attack_card.pop("_visual_slot", None)
        field_slot = len(state["fields"][attacker])
        _place_field(state, attacker, attack_card)
        _move_event(
            state,
            defender,
            attack_card,
            f"攻击无效，“{CARDS[attack_card['key']].name}”留在你的场上",
            source_zone="resolution",
            destination_zone="field",
            destination_owner=attacker,
            field_slot=field_slot,
        )
        _draw_available(state, defender, "royal", history_group=state.get("_active_history_group"))
        _refund_guarded_attack_action(state, attacker, attack_card)
        attack_card["_settled"] = True
        return True
    state["pending"] = {
        "type": "guard_trigger",
        "prompt": "对手发动攻击，是否使用卫兵？",
        "guard_uid": guards[0]["uid"],
        "attack_card": attack_card,
        "attacker": attacker,
        "effect": effect,
        "history_group": state.get("_active_history_group"),
        "options": [{"value": "use", "label": "使用卫兵"}, {"value": "pass", "label": "放弃"}],
    }
    return True


def _refund_guarded_attack_action(state: dict, attacker: str, attack_card: dict) -> None:
    """卫兵不制造行动差：仅返还这张攻击牌实际支付的行动点。"""

    paid = int(attack_card.pop("_paid_action_points", 0))
    if paid <= 0:
        return
    state["action_points"] += paid
    who = "你" if attacker == "player" else "对手"
    message = f"卫兵返还了{who}打出攻击牌消耗的 {paid} 个行动点"
    _log(state, message, "gold")


def _resolve_attack_effect(state: dict, player: str, card: dict, effect: dict) -> None:
    opponent = _other(player)
    key = card["key"]
    params = effect.get("params", {})
    if key == "mage":
        number = int(params.get("number", 0))
        if number not in {1, 2, 3, 4}:
            raise GameError("法师需要宣言 1 到 4", details={"required": "number"})
        # 对手法师宣言的数字对玩家可见，作为一条独立历史事件记录，避免后续 notice/move 里缺失该信息。
        if player == "ai":
            _event(
                state,
                "notice",
                "ai",
                f"对手的法师宣言 Lv.{number}",
                card=card,
                title="对方行动",
                skippable=False,
                record_history=True,
                animate=False,
            )
        matches = [c for c in state["hands"][opponent] if CARDS[c["key"]].level == number]
        if matches:
            # 被攻击方可以选择"放置 1 张 Lv=number 手牌到场上"，或"放弃 → 对方 +1 金币"。
            # 场满时无法放置，只能放弃；此时直接走 +1 金分支。
            can_place = _has_field_space(state, opponent)
            if opponent == "player" and can_place:
                # 挂起等待玩家响应，其余结算延后到 resolve。
                # 保存当前 history_group，resolve 时恢复，让 coin/move 事件与 play 归并到同一条日志。
                state["pending"] = {
                    "type": "mage_pick",
                    "prompt": f"对手的法师宣言 Lv.{number}，请选择：放置 1 张 Lv.{number} 手牌，或放弃并让对手获得 1 枚金币。",
                    "attack_card": card,
                    "attacker": player,
                    "number": number,
                    "matches": [c["uid"] for c in matches],
                    "history_group": state.get("_active_history_group"),
                    "options": [
                        {"value": "place", "label": f"放置 1 张 Lv.{number} 手牌"},
                        {"value": "pass", "label": "放弃，对方 +1 金币"},
                    ],
                }
                return
            # 情形 D：AI 打法师命中玩家但玩家场满 → 只能送金币，一条"对方行动"通知。
            if opponent == "player" and not can_place:
                _event(
                    state,
                    "notice",
                    "ai",
                    f"对手的法师宣言 Lv.{number}，命中但你场上已满，视为你放弃放置，对手获得 1 枚金币。",
                    card=card,
                    title="对方行动",
                    skippable=False,
                    record_history=False,
                    animate=False,
                )
                _gain_coin(state, player, 1, "法师（被攻击方场满）", source_card=card)
                return
            # 情形 A：player 打法师命中 AI → AI 内部决策 place/pass。
            worst = min(matches, key=_ai_card_value)
            pass_cost = 60 + (40 if state["coins"]["ai"] >= 3 else 0)
            if state["coins"]["ai"] == 4:
                pass_cost = 200
            place_cost = _ai_card_value(worst)
            if not (can_place and place_cost <= pass_cost):
                _event(
                    state,
                    "notice",
                    player,
                    f"宣言 Lv.{number}：命中，但对手放弃放置。",
                    card=card,
                    animate=False,
                )
                _gain_coin(state, player, 1, "法师（对手放弃放置）", source_card=card)
                return
            chosen = worst
            _event(
                state,
                "notice",
                player,
                f"宣言 Lv.{number}：命中。",
                card=card,
                animate=False,
            )
            chosen = _find_and_pop(state["hands"][opponent], chosen["uid"])
            field_slot = len(state["fields"][opponent])
            _place_field(state, opponent, chosen)
            _move_event(
                state,
                player,
                chosen,
                f"对手放置「{CARDS[chosen['key']].name}」。",
                source_zone="hand",
                destination_zone="field",
                source_owner=opponent,
                destination_owner=opponent,
                field_slot=field_slot,
                record_history=True,
            )
            _log(state, "对手放置了 1 张 Lv 手牌")
        else:
            if player == "ai":
                _event(
                    state,
                    "notice",
                    "ai",
                    f"对手的法师宣言 Lv.{number}，未命中并获得 1 枚金币。",
                    card=card,
                    title="对方行动",
                    skippable=False,
                    record_history=False,
                    animate=False,
                )
            else:
                _event(
                    state,
                    "notice",
                    player,
                    f"宣言 Lv.{number}：未命中。",
                    card=card,
                    animate=False,
                )
            _gain_coin(state, player, 1, "法师", source_card=card)
    elif key in {"hero4", "hero5", "hero_crest"}:
        sword = next((c for c in state["fields"][player] if c["key"] == "holy_sword" and not c.get("tapped")), None)
        if params.get("use_holy_sword"):
            if not sword:
                raise GameError("当前没有可发动的圣剑")
            field_target_uid = params.get("field_target_uid")
            field_targets = state["fields"][opponent]
            field_target = next((c for c in field_targets if c["uid"] == field_target_uid), None)
            if field_target is None:
                raise GameError("请选择对手场上的一张牌", details={"required": "field_target_uid"})
            sword["tapped"] = True
            _event(state, "tap", player, "圣剑横置并改变勇者效果", card=sword, tapped=True)
            field_slot = field_targets.index(field_target)
            field_target = _find_and_pop(field_targets, field_target["uid"])
            _event(
                state,
                "discard",
                player,
                f"“{CARDS[field_target['key']].name}”被置入弃牌区",
                card=field_target,
                field_slot=field_slot,
                source_owner=opponent,
                destination=f"{CARDS[field_target['key']].faction}_discard",
                source_zone="field",
                destination_zone=f"{CARDS[field_target['key']].faction}_discard",
                record_history=True,
            )
            _discard(state, field_target)
            played_level = CARDS[key].level
            target_level = CARDS[field_target["key"]].level
            if played_level is not None and target_level is not None and played_level > target_level:
                _gain_coin(state, player, 1, "圣剑", source_card=sword)
            _log(state, "圣剑改变了勇者的效果，丢弃对手场上 1 张牌", "royal")
            return
        eligible = [c for c in state["hands"][opponent] if CARDS[c["key"]].faction != "royal"]
        target_uid = params.get("target_uid")
        if not eligible:
            raise GameError("勇者没有合法目标")
        target = next((c for c in eligible if c["uid"] == target_uid), None)
        if target is None:
            if player == "ai":
                target = _rng(state).choice(eligible)
            else:
                raise GameError("请选择一张合法牌背", details={"required": "target_uid"})
        target = _find_and_pop(state["hands"][opponent], target["uid"])
        target_def = CARDS[target["key"]]
        field_slot = len(state["fields"][opponent])
        _place_field(state, opponent, target)
        _move_event(
            state,
            player,
            target,
            f"{'你' if opponent == 'player' else '对手'}将“{target_def.name}”从手牌放置到场上",
            source_zone="hand",
            destination_zone="field",
            source_owner=opponent,
            destination_owner=opponent,
            field_slot=field_slot,
        )
        hero = CARDS[key]
        wins = (hero.level is not None and target_def.level is not None and hero.level > target_def.level) or (
            key == "hero_crest" and (target_def.level is not None or "monster" in target_def.crests)
        )
        if wins:
            _gain_coin(state, player, 1, "勇者", source_card=card)
    elif key == "bat":
        if player == "ai":
            state["ai_memory"]["known_player_hand"] = [c["uid"] for c in state["hands"]["player"]]
        else:
            _event(
                state,
                "notice",
                player,
                f"蝙蝠查看对手当前的 {len(state['hands'][opponent])} 张手牌",
                title="查看对手手牌",
                revealed_cards=state["hands"][opponent],
                skippable=False,
            )
        returned = state["fields"][opponent][:]
        state["fields"][opponent].clear()
        for field_slot, target in enumerate(returned):
            target["tapped"] = False
            target["_ai_revealed"] = True  # 曾在场上，对双方公开
            state["hands"][opponent].append(target)
            if opponent == "player":
                _ai_remember_player_card(state, target)
            _move_event(
                state,
                player,
                target,
                f"“{CARDS[target['key']].name}”从场上返回手牌",
                source_zone="field",
                destination_zone="hand",
                source_owner=opponent,
                destination_owner=opponent,
                field_slot=field_slot,
            )
        _log(state, f"蝙蝠查看手牌并令对手场上的 {len(returned)} 张牌回到手牌", "monster")
    elif key == "witch":
        card_name = params.get("card_name")
        if card_name not in CARD_NAMES:
            raise GameError("女巫需要宣言一个有效牌名", details={"required": "card_name", "options": CARD_NAMES})
        zones = (state["hands"][opponent], state["fields"][opponent])
        found = next(((zone, c) for zone in zones for c in zone if CARDS[c["key"]].name == card_name), None)
        if found:
            zone, target = found
            location = "手牌" if zone is state["hands"][opponent] else "场上"
            if player == "ai":
                _event(
                    state,
                    "notice",
                    "ai",
                    f"对手的女巫宣言「{card_name}」，命中你的{location}。",
                    card=card,
                    title="对方行动",
                    skippable=False,
                    record_history=False,
                )
            else:
                _event(
                    state,
                    "notice",
                    player,
                    f"宣言「{card_name}」：命中{location}并取得。",
                    card=card,
                )
            source_zone = "hand" if zone is state["hands"][opponent] else "field"
            field_slot = zone.index(target) if source_zone == "field" else None
            target = _find_and_pop(zone, target["uid"])
            target["_ai_revealed"] = True  # 女巫宣言的名字对双方公开
            state["hands"][player].append(target)
            move_message = (
                f"对手的女巫取得“{CARDS[target['key']].name}”并加入手牌"
                if player == "ai"
                else f"女巫取得“{CARDS[target['key']].name}”并加入手牌"
            )
            _move_event(
                state,
                player,
                target,
                move_message,
                source_zone=source_zone,
                destination_zone="hand",
                source_owner=opponent,
                destination_owner=player,
                field_slot=field_slot,
                record_history=True,
            )
            _log(state, f"女巫宣言“{card_name}”并取得 1 张牌", "monster")
        else:
            if player == "ai":
                _event(
                    state,
                    "notice",
                    "ai",
                    f"对手的女巫宣言「{card_name}」，未命中。",
                    card=card,
                    title="对方行动",
                    skippable=False,
                    record_history=True,
                )
            else:
                _event(state, "notice", player, f"宣言「{card_name}」：未命中。", card=card)
            _log(state, f"女巫宣言“{card_name}”，但没有命中")
    elif key == "goblin":
        if state["coins"][opponent] <= state["coins"][player]:
            raise GameError("哥布林没有合法目标")
        state["coins"][opponent] -= 1
        transfer_message = "对手向你交付 1 枚金币" if player == "player" else "你向对手交付 1 枚金币"
        _gain_coin(
            state,
            player,
            1,
            "哥布林",
            source_card=card,
            event_message=transfer_message,
        )
    elif key == "dragonfire":
        target_uid = params.get("target_uid")
        targets = state["fields"][opponent]
        target = next((c for c in targets if c["uid"] == target_uid), None)
        if target is None:
            if player == "ai" and targets:
                target = targets[0]
            else:
                raise GameError("龙炎需要选择对手场上的牌", details={"required": "target_uid"})
        field_slot = targets.index(target)
        target = _find_and_pop(targets, target["uid"])
        _event(
            state,
            "discard",
            player,
            f"“{CARDS[target['key']].name}”被置入弃牌区",
            card=target,
            field_slot=field_slot,
            source_owner=opponent,
            destination=f"{CARDS[target['key']].faction}_discard",
            source_zone="field",
            destination_zone=f"{CARDS[target['key']].faction}_discard",
            record_history=True,
        )
        _discard(state, target)
        if CARDS[target["key"]].level is not None:
            _gain_coin(state, player, 1, "龙炎", source_card=card)


def _resolve_effect(state: dict, player: str, card: dict, params: dict) -> None:
    key = card["key"]
    if key == "blacksmith":
        uids = params.get("card_uids") or []
        if len(uids) != 2 or len(set(uids)) != 2:
            raise GameError("铁匠需要选择 2 张手牌", details={"required": "card_uids", "count": 2})
        placed = [_find_and_pop(state["hands"][player], uid) for uid in uids]
        for target in placed:
            field_slot = len(state["fields"][player])
            _place_field(state, player, target)
            _move_event(
                state,
                player,
                target,
                f"铁匠将“{CARDS[target['key']].name}”从手牌放置到场上",
                source_zone="hand",
                destination_zone="field",
                source_owner=player,
                destination_owner=player,
                field_slot=field_slot,
            )
        if _same_mark(placed):
            _gain_coin(state, player, 1, "铁匠", source_card=card)
    elif key == "monk":
        options = [c for c in state["royal_discard"] if CARDS[c["key"]].level != 1]
        if options:
            uid = params.get("target_uid") or options[0]["uid"]
            target = next((c for c in options if c["uid"] == uid), None)
            if target is None:
                raise GameError("僧侣选择的弃牌无效")
            target = _find_and_pop(state["royal_discard"], target["uid"])
            target["_ai_revealed"] = True  # 从公开弃牌区取得
            state["hands"][player].append(target)
            if params.get("mode", "hand") == "play":
                _play_card(
                    state,
                    player,
                    target["uid"],
                    params.get("play_params") or {},
                    free=True,
                    source_zone="royal_discard",
                )
                _log(state, "僧侣从皇室弃牌区取回并免费打出 1 张牌", "royal")
            else:
                _move_event(
                    state,
                    player,
                    target,
                    f"僧侣将“{CARDS[target['key']].name}”从皇室弃牌区加入手牌",
                    source_zone="royal_discard",
                    destination_zone="hand",
                    destination_owner=player,
                )
                _log(state, "僧侣从皇室弃牌区取回 1 张牌", "royal")
    elif key == "skeleton":
        if state["monster_discard"]:
            uid = params.get("target_uid") or state["monster_discard"][0]["uid"]
            target = _find_and_pop(state["monster_discard"], uid)
            field_slot = len(state["fields"][player])
            _place_field(state, player, target)
            _move_event(
                state,
                player,
                target,
                f"白骨将“{CARDS[target['key']].name}”从魔物弃牌区放置到场上",
                source_zone="monster_discard",
                destination_zone="field",
                destination_owner=player,
                field_slot=field_slot,
            )
    elif key == "dragon_egg":
        target_key = params.get("target_key", "dragonfire")
        if target_key not in {"dragonfire", "fire_dragon"}:
            raise GameError("龙蛋的搜索目标无效")
        source_zone = "monster_discard"
        target = next((c for c in state["monster_discard"] if c["key"] == target_key), None)
        if target is None:
            source_zone = "monster_deck"
            target = next((c for c in state["monster_deck"] if c["key"] == target_key), None)
        if target:
            target = _find_and_pop(state[source_zone], target["uid"])
            target["_ai_revealed"] = True  # 龙蛋宣言目标牌名，对双方公开
            state["hands"][player].append(target)
            source_name = "魔物弃牌区" if source_zone == "monster_discard" else "魔物牌库"
            _move_event(
                state,
                player,
                target,
                f"龙蛋从{source_name}找到{CARDS[target_key].name}并加入手牌",
                source_zone=source_zone,
                destination_zone="hand",
                destination_owner=player,
            )
    elif CARDS[key].kind == "attack":
        effect = {"params": params}
        if _trigger_guard(state, player, card, effect):
            return
        _resolve_attack_effect(state, player, card, effect)


def _finish_played_card(state: dict, player: str, card: dict) -> None:
    field_slot = int(card.pop("_visual_slot", len(state["fields"][player])))
    if card.pop("_settled", False):
        return
    if state.get("pending") and state["pending"].get("attack_card", {}).get("uid") == card["uid"]:
        return
    card.pop("_paid_action_points", None)
    if CARDS[card["key"]].persistent:
        _place_field(state, player, card)
    else:
        faction = CARDS[card["key"]].faction
        _event(
            state,
            "discard",
            player,
            f"{'你' if player == 'player' else '对手'}将“{CARDS[card['key']].name}”置入弃牌区",
            card=card,
            field_slot=field_slot,
            source_owner=player,
            destination=f"{faction}_discard",
            source_zone="field",
            destination_zone=f"{faction}_discard",
        )
        _discard(state, card)


def _trigger_demon_after_play(state: dict, player: str, card: dict) -> None:
    """在卡牌及所有攻击响应结算完毕后触发魔王。"""
    demon_uid = card.pop("_demon_trigger_uid", None)
    if not demon_uid:
        return
    demon = next(
        (c for c in state["fields"][player] if c["uid"] == demon_uid and not c.get("tapped")),
        None,
    )
    if demon:
        demon["tapped"] = True
        _event(state, "tap", player, "魔王横置并发动效果", card=demon, tapped=True)
        _gain_coin(state, player, 1, "魔王", source_card=demon)


def _play_card(
    state: dict,
    player: str,
    uid: str,
    params: dict | None = None,
    *,
    free: bool = False,
    source_zone: str = "hand",
) -> None:
    params = params or {}
    hand = state["hands"][player]
    card = next((c for c in hand if c["uid"] == uid), None)
    if card is None:
        raise GameError("这张牌不在手牌中")
    if not _card_can_play(state, player, card, params, ignore_action_points=free):
        raise GameError("当前不能打出这张牌")
    definition = CARDS[card["key"]]
    demon_at_play = next(
        (held for held in state["fields"][player] if held["key"] == "demon_king" and not held.get("tapped")),
        None,
    )
    cost = 0 if free else 1
    # 先校验需要由玩家明确提供的参数，避免失败后部分修改状态。
    if player == "player":
        if card["key"] == "blacksmith" and len(params.get("card_uids") or []) != 2:
            raise GameError("铁匠需要选择 2 张手牌", details={"required": "card_uids", "count": 2})
        if card["key"] in {"hero4", "hero5", "hero_crest"} and params.get("use_holy_sword"):
            if not params.get("field_target_uid"):
                raise GameError("请先选择圣剑的合法目标", details={"required": "field_target_uid"})
        elif card["key"] in {"hero4", "hero5", "hero_crest", "dragonfire"} and not params.get("target_uid"):
            raise GameError("请先选择合法目标", details={"required": "target_uid"})
        if card["key"] == "mage" and params.get("number") not in {1, 2, 3, 4}:
            raise GameError("请选择要宣言的等级", details={"required": "number"})
        if card["key"] == "witch" and params.get("card_name") not in CARD_NAMES:
            raise GameError("请选择要宣言的牌名", details={"required": "card_name", "options": CARD_NAMES})
    card = _find_and_pop(hand, uid)
    previous_history_group = state.get("_active_history_group")
    state["_active_history_group"] = (
        f"play-{state['turn_number']}-{int(state.get('battle_history_sequence', 0)) + 1}-{card['uid']}"
    )
    if (
        demon_at_play
        and definition.faction == "monster"
        and definition.level is not None
        and card["key"] != "demon_king"
    ):
        card["_demon_trigger_uid"] = demon_at_play["uid"]
    field_slot = len(state["fields"][player])
    card["_visual_slot"] = field_slot
    card["_paid_action_points"] = cost
    state["action_points"] -= cost
    message = f"{'你' if player == 'player' else '对手'}打出“{definition.name}”"
    _log(state, message, definition.faction)
    _event(
        state,
        "play",
        player,
        message,
        card=card,
        field_slot=field_slot,
        source_owner=player if source_zone == "hand" else None,
        destination_owner=player,
        source_zone=source_zone,
        destination_zone="field",
    )
    _event(
        state,
        "effect",
        player,
        f"“{definition.name}”发动效果",
        card=card,
        field_slot=field_slot,
        source_owner=player,
    )
    _resolve_effect(state, player, card, params)
    if state["status"] == "playing":
        _finish_played_card(state, player, card)
    if state["status"] == "playing" and not state.get("pending"):
        _trigger_demon_after_play(state, player, card)
    if previous_history_group is None:
        state.pop("_active_history_group", None)
    else:
        state["_active_history_group"] = previous_history_group


def _prepare_turn(state: dict, player: str) -> None:
    state["current_player"] = player
    state["turn_number"] += 1
    state["phase"] = "prepare"
    state["action_points"] = 0
    prepare_message = f"{'你的' if player == 'player' else '对手的'}准备阶段"
    _event(
        state,
        "phase",
        player,
        prepare_message,
        phase="prepare",
        history_group=f"turn-divider-{state['turn_number']}",
        record_history=True,
        skippable=False,
    )
    field = state["fields"][player]
    returning = [(index, card) for index, card in enumerate(field) if not CARDS[card["key"]].persistent]
    state["fields"][player] = [c for c in field if CARDS[c["key"]].persistent]
    for field_slot, card in returning:
        card["tapped"] = False
        card["_ai_revealed"] = True  # 曾在场上，回手仍是公开的
        state["hands"][player].append(card)
        if player == "player":
            _ai_remember_player_card(state, card)
        _move_event(
            state,
            player,
            card,
            f"“{CARDS[card['key']].name}”在准备阶段从场上返回手牌",
            source_zone="field",
            destination_zone="hand",
            source_owner=player,
            destination_owner=player,
            field_slot=field_slot,
            history_group=f"prepare-return-{state['turn_number']}-{card['uid']}",
        )
    princess = next((c for c in state["fields"][player] if c["key"] == "princess"), None)
    if princess:
        princess_group = f"prepare-princess-{state['turn_number']}-{princess['uid']}"
        _event(
            state,
            "trigger",
            player,
            "公主在准备阶段发动效果",
            card=princess,
            history_group=princess_group,
            animate=False,
        )
        _gain_coin(
            state,
            player,
            1,
            "公主准备阶段效果",
            source_card=princess,
            history_group=princess_group,
        )
        if state["status"] != "playing":
            return
    grail = next((c for c in state["fields"][player] if c["key"] == "holy_grail"), None)
    if grail and state["coins"][player] == 4:
        _event(
            state,
            "trigger",
            player,
            "圣杯在准备阶段发动效果：满足胜利条件",
            card=grail,
            history_group=f"prepare-grail-{state['turn_number']}-{grail['uid']}",
        )
        _finish(state, player, "圣杯效果获胜")
        return
    state["phase"] = "main"
    state["action_points"] = 2
    message = f"{'你的' if player == 'player' else '对手的'}主要阶段开始，获得 2 个行动点"
    _log(state, message, "gold")
    _event(state, "phase", player, message, phase="main", skippable=False)


def _end_turn(state: dict, player: str, *, force: bool = False) -> None:
    if state["current_player"] != player or state["phase"] != "main":
        raise GameError("当前不能结束回合")
    if player == "player" and state["action_points"] > 0 and not force:
        raise GameError("仍有行动点，请确认提前结束回合", code="confirmation_required")
    state["phase"] = "discard"
    end_message = f"{'你的' if player == 'player' else '对手的'}结束阶段"
    _event(state, "phase", player, end_message, phase="end", skippable=False)
    if len(state["hands"][player]) > 4:
        if player == "player":
            state["pending"] = {
                "type": "discard",
                "prompt": f"请选择 {len(state['hands'][player]) - 4} 张手牌弃置。",
                "count": len(state["hands"][player]) - 4,
            }
            return
        while len(state["hands"][player]) > 4:
            # 留住卫兵、持续牌和高影响攻击牌，优先丢弃低价值手牌。
            # 用弃牌专用估值：留在手里不会立即暴露给玩家的解牌，因此不叠加"打出后被解"的惩罚。
            card = min(state["hands"][player], key=lambda held: _ai_hold_score(state, held))
            state["hands"][player].remove(card)
            destination = f"{CARDS[card['key']].faction}_discard"
            _discard(state, card)
            _event(
                state,
                "discard",
                player,
                f"对手在结束阶段将“{CARDS[card['key']].name}”置入弃牌区",
                card=card,
                source_owner=player,
                destination=destination,
                source_zone="hand",
                destination_zone=destination,
                history_group=f"end-discard-{state['turn_number']}-{card['uid']}",
                record_history=True,
            )
    for card in state["fields"][player]:
        was_tapped = card.get("tapped", False)
        card["tapped"] = False
        if was_tapped:
            _event(state, "tap", player, f"“{CARDS[card['key']].name}”恢复竖置", card=card, tapped=False)
    _prepare_turn(state, _other(player))


def _activate(state: dict, player: str, uid: str, params: dict | None = None) -> None:
    params = params or {}
    card = next((c for c in state["fields"][player] if c["uid"] == uid), None)
    if card is None or not CARDS[card["key"]].persistent or card.get("tapped"):
        raise GameError("该持续牌当前不能横置")
    previous_history_group = state.get("_active_history_group")
    state["_active_history_group"] = (
        f"activate-{state['turn_number']}-{int(state.get('battle_history_sequence', 0)) + 1}-{card['uid']}"
    )
    message = f"{'你' if player == 'player' else '对手'}横置“{CARDS[card['key']].name}”发动效果"
    _log(state, message)
    _event(state, "activate", player, message, card=card)
    if card["key"] == "king":
        options = [c for c in state["royal_discard"] if c["key"] == "hero4"]
        target_uid = params.get("target_uid")
        target = next((c for c in options if c["uid"] == target_uid), None) if target_uid else next(iter(options), None)
        if not target:
            raise GameError("皇室弃牌区没有 Lv.4 勇者")
        target = _find_and_pop(state["royal_discard"], target["uid"])
        state["hands"][player].append(target)
        _move_event(
            state,
            player,
            target,
            "国王将 Lv.4 勇者从皇室弃牌区加入手牌",
            source_zone="royal_discard",
            destination_zone="hand",
            destination_owner=player,
        )
    elif card["key"] == "fire_dragon":
        options = [c for c in state["monster_discard"] if c["key"] == "dragonfire"]
        target_uid = params.get("target_uid")
        target = next((c for c in options if c["uid"] == target_uid), None) if target_uid else next(iter(options), None)
        if not target:
            raise GameError("魔物弃牌区没有龙炎")
        if params.get("mode") == "play":
            field_target_uid = params.get("field_target_uid")
            if not any(c["uid"] == field_target_uid for c in state["fields"][_other(player)]):
                raise GameError("请选择龙炎的合法目标", details={"required": "field_target_uid"})
        target = _find_and_pop(state["monster_discard"], target["uid"])
        state["hands"][player].append(target)
        if params.get("mode") == "play":
            _play_card(
                state,
                player,
                target["uid"],
                {"target_uid": field_target_uid},
                free=True,
                source_zone="monster_discard",
            )
        else:
            _move_event(
                state,
                player,
                target,
                "火龙将龙炎从魔物弃牌区加入手牌",
                source_zone="monster_discard",
                destination_zone="hand",
                destination_owner=player,
            )
    else:
        raise GameError("这张持续牌没有主动横置效果")
    card["tapped"] = True
    _event(state, "tap", player, f"“{CARDS[card['key']].name}”横置", card=card, tapped=True)
    if previous_history_group is None:
        state.pop("_active_history_group", None)
    else:
        state["_active_history_group"] = previous_history_group


def _ai_params(state: dict, card: dict) -> dict:
    opponent = "player"
    key = card["key"]
    if key == "blacksmith":
        candidates = [c for c in state["hands"]["ai"] if c["uid"] != card["uid"]]
        pairs = [(left, right) for index, left in enumerate(candidates) for right in candidates[index + 1 :]]
        if pairs:
            pair = max(
                pairs,
                key=lambda item: _ai_blacksmith_pair_value(state, item),
            )
            return {"card_uids": [c["uid"] for c in pair]}
        return {"card_uids": []}
    if key == "mage":
        return {"number": _ai_mage_number(state)}
    if key in {"hero4", "hero5", "hero_crest"}:
        sword = next(
            (c for c in state["fields"]["ai"] if c["key"] == "holy_sword" and not c.get("tapped")),
            None,
        )
        sword_targets = _ai_sword_targets(state, card) if sword else []
        if sword_targets:
            target = max(sword_targets, key=lambda c: _ai_sword_target_value(state, card, c))
            return {"use_holy_sword": True, "field_target_uid": target["uid"]}
        eligible = [c for c in state["hands"][opponent] if CARDS[c["key"]].faction != "royal"]
        known = {uid for uid in state["ai_memory"]["known_player_hand"]}
        known_eligible = [c for c in eligible if c["uid"] in known]
        scoring_known = [c for c in known_eligible if _ai_hero_target_value(card, c) >= 100]
        unknown_eligible = [c for c in eligible if c["uid"] not in known]
        if scoring_known:
            target = max(scoring_known, key=lambda c: _ai_hero_target_value(card, c))
            return {"target_uid": target["uid"]}
        if len(state["hands"]["ai"]) >= 4 and unknown_eligible:
            target = _rng(state).choice(unknown_eligible)
            return {"target_uid": target["uid"]}
        choices = known_eligible or eligible
        if not choices:
            return {}
        target = max(choices, key=lambda c: _ai_hero_target_value(card, c)) if known_eligible else _rng(state).choice(choices)
        return {"target_uid": target["uid"]}
    if key == "witch":
        known = {uid for uid in state["ai_memory"]["known_player_hand"]}
        targets = list(state["fields"][opponent])
        targets += [c for c in state["hands"][opponent] if c["uid"] in known]
        target = max(targets, key=lambda c: _ai_threat_value(state, c), default=None)
        return {"card_name": CARDS[target["key"]].name if target else _rng(state).choice(CARD_NAMES)}
    if key == "dragonfire":
        targets = state["fields"][opponent]
        target = max(targets, key=lambda c: _ai_public_target_value(c, card, state)) if targets else None
        return {"target_uid": target["uid"]} if target else {}
    if key == "skeleton":
        target = max(state["monster_discard"], key=_ai_card_value, default=None)
        return {"target_uid": target["uid"]} if target else {}
    if key == "monk":
        options = [c for c in state["royal_discard"] if CARDS[c["key"]].level != 1]
        target = max(options, key=_ai_card_value, default=None)
        if not target:
            return {}
        # 若找回的是勇者且此刻打出能稳赚金币，直接免费打出更优（一次行动完成两步）。
        if target["key"] in {"hero4", "hero5", "hero_crest"} and _ai_hero_gain(state, target) > 0:
            eligible = [c for c in state["hands"]["player"] if CARDS[c["key"]].faction != "royal"]
            known = set(state["ai_memory"]["known_player_hand"])
            scoring = [c for c in eligible if c["uid"] in known and _ai_hero_target_value(target, c) >= 100]
            if scoring and _has_field_space(state, "player"):
                best = max(scoring, key=lambda c: _ai_hero_target_value(target, c))
                return {
                    "target_uid": target["uid"],
                    "mode": "play",
                    "play_params": {"target_uid": best["uid"]},
                }
        return {"target_uid": target["uid"], "mode": "hand"}
    if key == "dragon_egg":
        owns_fire_dragon = any(
            c["key"] == "fire_dragon" for c in state["hands"]["ai"] + state["fields"]["ai"]
        )
        preferred_key = "dragonfire" if owns_fire_dragon or _ai_dragon_egg_needs_dragonfire(state) else "fire_dragon"
        for target_key in (preferred_key, "dragonfire", "fire_dragon"):
            if any(c["key"] == target_key for c in state["monster_discard"]):
                return {"target_key": target_key}
            if any(c["key"] == target_key for c in state["monster_deck"]):
                return {"target_key": target_key}
        return {"target_key": preferred_key}
    return {}


def _ai_card_value(card: dict) -> int:
    """对手对自己已知卡牌的保留/取得价值。"""
    definition = CARDS[card["key"]]
    # 按持续收益、即时金币、信息与联动能力定义基础价值。
    strategic_values = {
        "princess": 90,
        "demon_king": 82,
        "holy_grail": 24,
        "fire_dragon": 68,
        "holy_sword": 38,
        "king": 58,
        "guard": 56,
        "dragonfire": 52,
        "goblin": 50,
        "hero5": 49,
        "hero_crest": 48,
        "hero4": 46,
        "witch": 43,
        "mage": 42,
        "bat": 40,
        "dragon_egg": 38,
        "blacksmith": 35,
        "skeleton": 32,
        "monk": 30,
    }
    return strategic_values.get(card["key"], 20 + (definition.level or 0))


def _ai_blacksmith_placement_value(state: dict, card: dict) -> int:
    """评估铁匠放置单牌的收益；持续牌能省行动点并立即建立长期场面。"""
    definition = CARDS[card["key"]]
    if definition.persistent:
        value = 55 + _ai_card_value(card)
        if _ai_player_has_persistent_answer(state):
            # 对方已知能用女巫夺取或用龙炎处理时，贸然暴露持续牌很容易白送场面。
            value -= 85
        if card["key"] == "princess":
            value += 12 + state["coins"]["ai"] * 5
        elif card["key"] == "holy_grail":
            value += {0: 0, 1: 5, 2: 18, 3: 45, 4: 100}.get(state["coins"]["ai"], 0)
        return value
    if definition.kind == "trigger":
        return -60
    # 非持续牌被放置时不发动效果，下回合才回手；只适合作为赚币所需的低损耗搭档。
    return 15 - _ai_card_value(card) // 3


def _ai_blacksmith_pair_value(state: dict, pair: tuple[dict, dict]) -> int:
    cards = list(pair)
    coin_value = 125 if _same_mark(cards) else 0
    return coin_value + sum(_ai_blacksmith_placement_value(state, card) for card in cards)


def _ai_mage_number(state: dict) -> int:
    """结合蝙蝠记忆和公开牌，选择最可能直接得分的法师宣言。"""
    levels = (1, 2, 3, 4)
    known_uids = set(state["ai_memory"].get("known_player_hand", []))
    player_hand = state["hands"]["player"]
    known_hand = [c for c in player_hand if c["uid"] in known_uids]
    if len(known_hand) == len(player_hand):
        present = {CARDS[c["key"]].level for c in known_hand}
        missing = [level for level in levels if level not in present]
        if missing:
            return missing[0]
        return min(levels, key=lambda level: min(
            (_ai_card_value(c) for c in known_hand if CARDS[c["key"]].level == level),
            default=999,
        ))

    total_by_level = {
        level: sum(definition.copies for definition in CARD_DEFINITIONS if definition.level == level)
        for level in levels
    }
    visible = (
        state["hands"]["ai"] + state["fields"]["ai"] + state["fields"]["player"]
        + state["royal_discard"] + state["monster_discard"] + state["tavern_faceup"] + known_hand
    )
    visible_by_level = {
        level: sum(1 for card in visible if CARDS[card["key"]].level == level)
        for level in levels
    }
    return min(levels, key=lambda level: (total_by_level[level] - visible_by_level[level], level))


def _ai_mage_guaranteed_coin(state: dict) -> bool:
    known = set(state["ai_memory"].get("known_player_hand", []))
    hand = state["hands"]["player"]
    if any(card["uid"] not in known for card in hand):
        return False
    declared = _ai_mage_number(state)
    return not any(CARDS[card["key"]].level == declared for card in hand)


def _ai_hero_target_value(hero: dict, target: dict) -> int:
    hero_def = CARDS[hero["key"]]
    target_def = CARDS[target["key"]]
    earns_coin = (
        hero_def.level is not None and target_def.level is not None and hero_def.level > target_def.level
    ) or (
        hero["key"] == "hero_crest" and (target_def.level is not None or "monster" in target_def.crests)
    )
    return (100 if earns_coin else 0) + _ai_card_value(target)


def _ai_public_target_value(target: dict, source: dict, state: dict | None = None) -> int:
    definition = CARDS[target["key"]]
    # 有 state 上下文时，用威胁值可以识别"即将触发胜利"的持续牌等紧急情况；
    # 没有时退化为基础价值，保持旧行为。
    base = _ai_threat_value(state, target) if state is not None else _ai_card_value(target)
    if source["key"] == "dragonfire":
        return base + (100 if definition.level is not None else 0)
    if source["key"] in {"hero4", "hero5", "hero_crest"}:
        return _ai_hero_target_value(source, target)
    return base


def _ai_threat_value(state: dict, card: dict) -> int:
    """评估一张对手牌留在当前局面中会造成的威胁。"""
    key = card["key"]
    value = _ai_card_value(card)
    player_coins = state["coins"]["player"]
    if key == "princess":
        value += max(0, 5 - player_coins) * 12
        # 玩家已到 4 金：公主下回合会直接触发胜利，必须优先清除。
        if player_coins >= 4:
            value += 500
    elif key == "holy_grail":
        # 圣杯在玩家 4 金时下回合直接获胜；必须比其他任何目标都优先。
        if player_coins >= 4:
            value += 500
        elif player_coins >= 3:
            value += 70
    elif key == "demon_king":
        value += 10 * sum(
            1 for held in state["hands"]["player"]
            if held["uid"] in set(state["ai_memory"].get("known_player_hand", []))
            and CARDS[held["key"]].faction == "monster"
            and CARDS[held["key"]].level is not None
        )
    return value


def _ai_witch_gain(state: dict) -> int:
    known = set(state["ai_memory"].get("known_player_hand", []))
    targets = list(state["fields"]["player"])
    targets += [c for c in state["hands"]["player"] if c["uid"] in known]
    # 抢夺同时消除对手威胁并把牌转化为己方资源，按双向收益计算。
    return 2 * max((_ai_threat_value(state, card) for card in targets), default=0)


def _ai_dragonfire_gain(state: dict) -> int:
    if not state["fields"]["player"]:
        return 0
    target = max(state["fields"]["player"], key=lambda c: _ai_public_target_value(c, {"key": "dragonfire"}, state))
    coin_bonus = 65 if CARDS[target["key"]].level is not None else 0
    return _ai_threat_value(state, target) + coin_bonus + 30  # 永久移除优于暂时弹回手牌


def _ai_dragon_egg_needs_dragonfire(state: dict) -> bool:
    """墓地没有龙炎且对方已有值得立即处理的目标时，龙蛋优先从牌库找龙炎。"""
    if any(card["key"] == "dragonfire" for card in state["monster_discard"]):
        return False
    return any(
        _ai_public_target_value(target, {"key": "dragonfire"}, state) >= 55
        for target in state["fields"]["player"]
    )


def _ai_hero_gain(state: dict, hero: dict) -> int:
    """只依据已确认的玩家手牌，评估勇者能够稳定得分的收益。"""
    known = set(state["ai_memory"].get("known_player_hand", []))
    targets = [
        card for card in state["hands"]["player"]
        if card["uid"] in known and CARDS[card["key"]].faction != "royal"
    ]
    if not targets:
        return 0
    best = max(_ai_hero_target_value(hero, target) for target in targets)
    earns_coin = best >= 100
    if not earns_coin:
        return 0
    return best + 80 + (100 if state["coins"]["ai"] == 4 else 0)


def _ai_hero_storage_penalty(state: dict, hero: dict) -> int:
    """勇者储备惩罚：AI 已知玩家手牌里没有能让本勇者得分的目标时，
    储备价值下调；known 集合为空视为信息不足，不惩罚。"""
    known = set(state["ai_memory"].get("known_player_hand", []))
    known_hand = [card for card in state["hands"]["player"] if card["uid"] in known]
    if not known_hand:
        return 0
    # known_hand 全为皇室：勇者对整个已知手牌都无目标；
    # 或存在非皇室但没有一张能让本勇者得分：勇者当前也无收益。
    if any(
        CARDS[card["key"]].faction != "royal"
        and _ai_hero_target_value(hero, card) >= 100
        for card in known_hand
    ):
        return 0
    unknown_count = len(state["hands"]["player"]) - len(known_hand)
    # 已知覆盖越完整，惩罚越大；剩余未知的手牌可能仍是非皇室，保留少量储备价值。
    if unknown_count <= 0:
        return -60
    if unknown_count == 1:
        return -40
    return -25


def _ai_sword_target_value(state: dict, hero: dict, target: dict) -> int:
    hero_level = CARDS[hero["key"]].level
    target_level = CARDS[target["key"]].level
    earns_coin = hero_level is not None and target_level is not None and hero_level > target_level
    return _ai_threat_value(state, target) + (120 if earns_coin else 0)


def _ai_sword_candidate_targets(state: dict, hero: dict) -> list[dict]:
    hero_level = CARDS[hero["key"]].level
    targets = []
    for target in state["fields"]["player"]:
        definition = CARDS[target["key"]]
        stable_coin = hero_level is not None and definition.level is not None and hero_level > definition.level
        high_persistent = definition.persistent and _ai_threat_value(state, target) >= 55
        if stable_coin or high_persistent:
            targets.append(target)
    return targets


def _ai_sword_targets(state: dict, hero: dict) -> list[dict]:
    sword = next(
        (card for card in state["fields"]["ai"] if card["key"] == "holy_sword" and not card.get("tapped")),
        None,
    )
    return _ai_sword_candidate_targets(state, hero) if sword else []


def _ai_sword_hero_gain(state: dict, hero: dict) -> int:
    targets = _ai_sword_targets(state, hero)
    return max((_ai_sword_target_value(state, hero, target) for target in targets), default=0)


def _ai_holy_sword_gain(state: dict) -> int:
    heroes = [card for card in state["hands"]["ai"] if card["key"] in {"hero4", "hero5", "hero_crest"}]
    gains = [
        _ai_sword_target_value(state, hero, target)
        for hero in heroes
        for target in _ai_sword_candidate_targets(state, hero)
    ]
    return max(gains, default=0)


def _ai_goblin_gain(state: dict) -> int:
    if state["coins"]["player"] <= state["coins"]["ai"]:
        return 0
    # 对方失去1分、己方获得1分，按两分差而非普通单次得分估值。
    return 120 + min(30, (state["coins"]["player"] - state["coins"]["ai"]) * 10)


def _ai_bat_gain(state: dict) -> int:
    field = state["fields"]["player"]
    if not field and not state["hands"]["player"]:
        return 0
    known = set(state["ai_memory"].get("known_player_hand", []))
    unknown_cards = sum(1 for card in state["hands"]["player"] if card["uid"] not in known)
    # 弹回持续牌等同于暂时关闭其收益；一次处理多张时额外加权。
    bounced = sum(_ai_threat_value(state, card) * 45 // 100 for card in field)
    persistent_count = sum(1 for card in field if CARDS[card["key"]].persistent)
    return bounced + persistent_count * 10 + unknown_cards * 8 + max(0, len(field) - 1) * 18


def _ai_monk_gain(state: dict) -> int:
    options = [card for card in state["royal_discard"] if CARDS[card["key"]].level != 1]
    target = max(options, key=_ai_card_value, default=None)
    if not target:
        return 0
    # 僧侣的总价值提升到最高合法目标，而不是与目标价值重复相加。
    return max(0, _ai_card_value(target) - _ai_card_value({"key": "monk"}))


def _ai_skeleton_gain(state: dict) -> int:
    target = max(state["monster_discard"], key=_ai_card_value, default=None)
    if not target:
        return 0
    # 白骨的总价值提升到墓地最高价值魔物，不重复计算目标价值。
    return max(0, _ai_card_value(target) - _ai_card_value({"key": "skeleton"}))


def _ai_has_high_value_skeleton_target(state: dict) -> bool:
    """女巫及以上价值的魔物值得立即用白骨回收，避免行动点被摸牌占用。"""
    best_value = max((_ai_card_value(card) for card in state["monster_discard"]), default=0)
    return best_value >= _ai_card_value({"key": "witch"})


def _ai_guard_gain(state: dict) -> int:
    protected = [card for card in state["fields"]["ai"] if CARDS[card["key"]].persistent]
    if not protected:
        return 0
    total = sum(_ai_card_value(card) for card in protected)
    critical = sum(1 for card in protected if card["key"] in {"princess", "demon_king", "holy_grail"})
    fire_dragon = any(card["key"] == "fire_dragon" for card in protected)
    dragonfire_ready = any(card["key"] == "dragonfire" for card in state["monster_discard"])
    # 卫兵挡下等级攻击牌后，该牌留在对方场上；火龙可免费回收龙炎将其转化为1分。
    fire_dragon_combo = (55 if fire_dragon else 0) + (55 if fire_dragon and dragonfire_ready else 0)
    return total * 45 // 100 + critical * 20 + fire_dragon_combo


def _ai_king_gain(state: dict) -> int:
    hero = next((card for card in state["royal_discard"] if card["key"] == "hero4"), None)
    if not hero:
        return 0
    return _ai_card_value(hero) + _ai_hero_gain(state, hero)


def _ai_fire_dragon_gain(state: dict) -> int:
    dragonfire = next((card for card in state["monster_discard"] if card["key"] == "dragonfire"), None)
    if not dragonfire:
        return 0
    value = _ai_card_value(dragonfire)
    if state["fields"]["player"] and _has_field_space(state, "ai"):
        # 火龙落场后即可免费打出龙炎，计入本回合即时破坏与得分收益。
        value += _ai_dragonfire_gain(state) + 45
    return value


def _ai_hold_score(state: dict, card: dict) -> int:
    """AI 弃牌时评估手牌保留价值。与 _ai_score 的区别：不减去"打出后被解"的惩罚，
    因为留在手里的持续牌本身没有暴露风险。"""
    key = card["key"]
    score = _ai_card_value(card)
    if key in {"princess", "demon_king", "fire_dragon", "holy_grail", "holy_sword"}:
        score += 30
    if key == "princess":
        score += max(0, 4 - state["coins"]["ai"]) * 8
    if key == "guard":
        # 卫兵是纯防御性资源，即使当前没有攻击也值得保留一张。
        score += 20
    return score


def _ai_score(state: dict, card: dict) -> int:
    key = card["key"]
    score = _ai_card_value(card)
    if CARDS[key].persistent and _ai_player_has_persistent_answer(state):
        score -= 85
    if key in {"goblin", "dragonfire", "hero4", "hero5", "hero_crest", "mage"}:
        score += 35
    if key in {"princess", "demon_king", "fire_dragon", "holy_grail", "holy_sword"}:
        score += 20
    if state["coins"]["ai"] == 4 and key in {"mage", "goblin", "dragonfire", "hero4", "hero5", "hero_crest"}:
        score += 100
    if key == "princess":
        score += max(0, 4 - state["coins"]["ai"]) * 8
    if key == "holy_grail":
        score += {0: 0, 1: 4, 2: 18, 3: 42, 4: 190}.get(state["coins"]["ai"], 0)
    if key == "demon_king":
        score += 12 * sum(
            1 for held in state["hands"]["ai"]
            if CARDS[held["key"]].faction == "monster" and CARDS[held["key"]].level is not None
        )
    if key == "witch":
        score += _ai_witch_gain(state)
    elif key == "dragonfire":
        score += _ai_dragonfire_gain(state)
    elif key == "bat":
        score += _ai_bat_gain(state)
    elif key in {"hero4", "hero5", "hero_crest"}:
        score += _ai_hero_gain(state, card) + _ai_sword_hero_gain(state, card) + _ai_hero_storage_penalty(state, card)
    elif key == "monk":
        score += _ai_monk_gain(state)
    elif key == "skeleton":
        score += _ai_skeleton_gain(state)
    elif key == "guard":
        score += _ai_guard_gain(state)
    elif key == "king":
        score += _ai_king_gain(state)
    elif key == "fire_dragon":
        score += _ai_fire_dragon_gain(state)
    elif key == "mage" and _ai_mage_guaranteed_coin(state):
        score += 105
    elif key == "goblin":
        score += _ai_goblin_gain(state)
    elif key == "holy_sword":
        score += _ai_holy_sword_gain(state)
    elif key == "dragon_egg" and _ai_dragon_egg_needs_dragonfire(state):
        score += 80
    params = _ai_params(state, card)
    if key == "blacksmith" and len(params.get("card_uids", [])) == 2:
        chosen = [c for c in state["hands"]["ai"] if c["uid"] in params["card_uids"]]
        persistent_count = sum(1 for chosen_card in chosen if CARDS[chosen_card["key"]].persistent)
        score += 60 if _same_mark(chosen) else 0
        score += 65 * persistent_count
    if key == "dragonfire" and params.get("target_uid"):
        target = next(c for c in state["fields"]["player"] if c["uid"] == params["target_uid"])
        score += 45 if CARDS[target["key"]].level is not None else 0
    return score


def _ai_card_scores_coin(state: dict, card: dict) -> bool:
    """判断这张牌用 _ai_params 选定的目标是否会让 AI 立即获得 1 枚金币。
    仅涵盖打出即结算的攻击/普通牌；持续牌激活走 _ai_activate_persistent 另行处理。"""
    key = card["key"]
    params = _ai_params(state, card)
    if key in {"hero4", "hero5", "hero_crest"}:
        return _ai_hero_gain(state, card) > 0 or _ai_sword_hero_gain(state, card) > 0
    if key == "dragonfire":
        target_uid = params.get("target_uid")
        if not target_uid:
            return False
        target = next((c for c in state["fields"]["player"] if c["uid"] == target_uid), None)
        return target is not None and CARDS[target["key"]].level is not None
    if key == "mage":
        return _ai_mage_guaranteed_coin(state)
    if key == "goblin":
        return _ai_goblin_gain(state) > 0
    if key == "blacksmith":
        chosen_uids = set(params.get("card_uids", []))
        if len(chosen_uids) != 2:
            return False
        chosen = [c for c in state["hands"]["ai"] if c["uid"] in chosen_uids]
        return len(chosen) == 2 and _same_mark(chosen)
    return False


PLAYER_SCORING_PERSISTENTS = {"princess", "demon_king"}


def _ai_disrupts_player_scoring(state: dict, card: dict) -> bool:
    """判断这张牌是否会立即移除玩家场上的公主/魔王等持续得分手段。"""
    scoring_persistents = [
        target for target in state["fields"]["player"]
        if target["key"] in PLAYER_SCORING_PERSISTENTS
    ]
    if not scoring_persistents:
        return False
    key = card["key"]
    params = _ai_params(state, card)
    if key == "dragonfire":
        target_uid = params.get("target_uid")
        return any(t["uid"] == target_uid for t in scoring_persistents)
    if key == "witch":
        name = params.get("card_name")
        return any(CARDS[t["key"]].name == name for t in scoring_persistents)
    if key in {"hero4", "hero5", "hero_crest"} and params.get("use_holy_sword"):
        target_uid = params.get("field_target_uid")
        return any(t["uid"] == target_uid for t in scoring_persistents)
    return False


def _ai_play_priority(state: dict, card: dict) -> tuple[int, int]:
    """优先使用会因比分变化而失效的牌，再比较通常的场面估值。"""
    ai_coins = state["coins"]["ai"]
    player_coins = state["coins"]["player"]
    # 赛点场景：AI 4 分时得分即胜，优先级最高；玩家 4 分时破坏其持续得分手段次之。
    if ai_coins == 4 and _ai_card_scores_coin(state, card):
        return (4, _ai_score(state, card))
    if player_coins == 4 and _ai_disrupts_player_scoring(state, card):
        return (3, _ai_score(state, card))
    goblin_window = (
        card["key"] == "goblin"
        and ai_coins < player_coins
    )
    skeleton_window = card["key"] == "skeleton" and _ai_has_high_value_skeleton_target(state)
    urgent_window = 2 if goblin_window else 1 if skeleton_window else 0
    return (urgent_window, _ai_score(state, card))


def _ai_preferred_scoring_hero(state: dict, playable: list[dict]) -> dict | None:
    """电脑决定用勇者得分后，优先消耗更容易被国王回收的 Lv.4 勇者。"""
    hero_order = {"hero4": 0, "hero5": 1, "hero_crest": 2}
    scoring_heroes = [
        card for card in playable
        if card["key"] in hero_order and _ai_hero_gain(state, card) > 0
    ]
    if not scoring_heroes:
        return None
    # 只在常规最高优先行动本来就是稳定得分勇者时替换勇者种类，
    # 不让该规则越过龙炎等更紧急的场面处理。
    normal_best = max(playable, key=lambda card: _ai_play_priority(state, card))
    if normal_best not in scoring_heroes:
        return None
    return min(scoring_heroes, key=lambda card: hero_order[card["key"]])


def _ai_activate_persistent(state: dict) -> bool:
    king = next((c for c in state["fields"]["ai"] if c["key"] == "king" and not c.get("tapped")), None)
    hero = next((c for c in state["royal_discard"] if c["key"] == "hero4"), None)
    if king and hero:
        _activate(state, "ai", king["uid"], {"target_uid": hero["uid"]})
        return True
    dragon = next((c for c in state["fields"]["ai"] if c["key"] == "fire_dragon" and not c.get("tapped")), None)
    dragonfire = next((c for c in state["monster_discard"] if c["key"] == "dragonfire"), None)
    if dragon and dragonfire:
        if state["fields"]["player"] and _has_field_space(state, "ai"):
            target = max(state["fields"]["player"], key=lambda c: _ai_public_target_value(c, dragonfire, state))
            _activate(state, "ai", dragon["uid"], {
                "target_uid": dragonfire["uid"], "mode": "play", "field_target_uid": target["uid"]
            })
        else:
            _activate(state, "ai", dragon["uid"], {"target_uid": dragonfire["uid"], "mode": "hand"})
        return True
    return False


def _ai_tavern_card_value(state: dict, card: dict) -> int:
    value = _ai_card_value(card)
    if card["key"] == "dragonfire" and state["fields"]["player"]:
        value += _ai_dragonfire_gain(state)
    elif card["key"] in {"hero4", "hero5", "hero_crest"}:
        value += _ai_hero_gain(state, card) + _ai_sword_hero_gain(state, card) + _ai_hero_storage_penalty(state, card)
        if any(
            held["key"] == "holy_sword" and not held.get("tapped")
            for held in state["fields"]["ai"]
        ):
            value += 85  # 已有圣剑时优先储备勇者，但不代表立即打出
    elif card["key"] == "monk":
        value += _ai_monk_gain(state)
    elif card["key"] == "skeleton":
        value += _ai_skeleton_gain(state)
    elif card["key"] == "guard":
        value += _ai_guard_gain(state)
    elif card["key"] == "king":
        value += _ai_king_gain(state)
    elif card["key"] == "fire_dragon":
        value += _ai_fire_dragon_gain(state)
    elif card["key"] == "mage" and _ai_mage_guaranteed_coin(state):
        value += 105
    elif card["key"] == "goblin":
        value += _ai_goblin_gain(state)
    elif card["key"] == "witch":
        value += _ai_witch_gain(state)
    elif card["key"] == "bat":
        value += _ai_bat_gain(state)
    return value


def _ai_deck_value(state: dict, faction: str) -> int:
    """依据当前场面估算从某阵营牌库抽牌的战略价值，不读取牌库顺序。"""
    value = 30
    opponent_persistent = [
        card for card in state["fields"]["player"] if CARDS[card["key"]].persistent
    ]
    own_persistent = [
        card for card in state["fields"]["ai"] if CARDS[card["key"]].persistent
    ]
    if faction == "monster":
        if any(card["key"] == "demon_king" for card in own_persistent):
            value += 130
        if opponent_persistent:
            highest_threat = max(_ai_threat_value(state, card) for card in opponent_persistent)
            # 女巫可抢夺、龙炎可永久移除、蝙蝠可群体弹回。
            value += 55 + highest_threat // 3 + max(0, len(opponent_persistent) - 1) * 18
        if state["coins"]["player"] > state["coins"]["ai"]:
            value += 28  # 哥布林能够制造两分差
    else:
        if own_persistent:
            value += _ai_guard_gain(state) // 2 + 25
        if any(card["key"] == "fire_dragon" for card in own_persistent):
            value += 50 + (40 if any(card["key"] == "dragonfire" for card in state["monster_discard"]) else 0)
        if any(card["key"] == "holy_sword" and not card.get("tapped") for card in own_persistent):
            value += 105
        if _ai_mage_guaranteed_coin(state):
            value += 55
        hero_probe = {"uid": "ai-royal-probe", "key": "hero4", "tapped": False}
        hero_gain = _ai_hero_gain(state, hero_probe)
        if hero_gain:
            value += 45 + hero_gain // 4
        if state["coins"]["ai"] == 4:
            value += 35
    return value


def _ai_draw_source(state: dict) -> str:
    deck_scores = {
        "royal": _ai_deck_value(state, "royal") if state["royal_deck"] else -1,
        "monster": _ai_deck_value(state, "monster") if state["monster_deck"] else -1,
    }
    best_deck = max(deck_scores, key=deck_scores.get)
    if state["tavern_faceup"]:
        best_index, best_card = max(
            enumerate(state["tavern_faceup"]), key=lambda item: _ai_tavern_card_value(state, item[1])
        )
        # 公开牌是确定收益，略微优于牌库期望时直接取得。
        tavern_value = _ai_tavern_card_value(state, best_card)
        if tavern_value >= 100 or tavern_value >= max(32, deck_scores[best_deck] + 8):
            return f"tavern:{best_index}"
    if deck_scores[best_deck] >= 0:
        return best_deck
    return f"tavern:0" if state["tavern_faceup"] else best_deck


def _ai_player_has_persistent_answer(state: dict) -> bool:
    """玩家公开或已知资源中，是否已有可靠手段处理对手的持续牌。"""
    reusable_dragonfire = (
        any(card["key"] == "fire_dragon" for card in state["fields"]["player"])
        and any(card["key"] == "dragonfire" for card in state["monster_discard"])
    )
    known_uids = set(state["ai_memory"].get("known_player_hand", []))
    known_answer = any(
        card["uid"] in known_uids and card["key"] in {"witch", "dragonfire"}
        for card in state["hands"]["player"]
    )
    return reusable_dragonfire or known_answer


def _ai_should_take_tavern(state: dict) -> bool:
    """有余裕时主动取得高价值公开牌，而不是只在无牌可打时抽牌。"""
    if state["action_points"] < 2 or len(state["hands"]["ai"]) >= 4 or not state["tavern_faceup"]:
        return False
    best_tavern = max(_ai_tavern_card_value(state, card) for card in state["tavern_faceup"])
    playable = [card for card in state["hands"]["ai"] if _card_can_play(state, "ai", card)]
    # 会随比分变化失效的哥布林，以及墓地已有高价值目标的白骨，必须先兑现；
    # 否则只剩 1 行动点时会被酒馆摸牌永久挤掉。
    if any(_ai_play_priority(state, card)[0] > 0 for card in playable):
        return False
    best_play = max((_ai_score(state, card) for card in playable), default=0)
    # 卫兵、龙炎、哥布林等高影响牌会主动争夺；普通牌仅在明显优于手牌时拿取。
    return best_tavern >= 46 or best_tavern >= best_play + 8


def _ai_should_hold_card(state: dict, card: dict) -> bool:
    """保留当前收益不足、但后续可能形成高价值联动的战术牌。"""
    key = card["key"]
    if CARDS[key].persistent:
        if not _ai_player_has_persistent_answer(state):
            return False
        # 只有能在本回合立刻兑现价值的持续牌值得冒龙炎风险放下。
        if key == "king":
            return not any(target["key"] == "hero4" for target in state["royal_discard"])
        if key == "fire_dragon":
            return not any(target["key"] == "dragonfire" for target in state["monster_discard"])
        if key == "demon_king" and state["action_points"] >= 2:
            return not any(
                CARDS[target["key"]].faction == "monster"
                and CARDS[target["key"]].level is not None
                and _card_can_play(state, "ai", target)
                for target in state["hands"]["ai"]
                if target["uid"] != card["uid"]
            )
        return True
    if key == "witch":
        # 有已知目标或对方场上有可抢牌时立即用；手牌满时也别继续囤，先出手创造信息。
        if _ai_witch_gain(state) > 0 or state["fields"]["player"]:
            return False
        return len(state["hands"]["ai"]) < 4
    if key == "bat":
        # 蝙蝠在对方场上有牌 or 未查过对手手牌时都值得打；只有完全没价值时才留。
        if not state["hands"]["player"] and not state["fields"]["player"]:
            return True
        known = set(state["ai_memory"].get("known_player_hand", []))
        all_player_cards_known = state["hands"]["player"] and all(
            c["uid"] in known for c in state["hands"]["player"]
        )
        if state["fields"]["player"] or not all_player_cards_known:
            return False
        return _ai_bat_gain(state) < 24
    if key == "monk":
        return not any(CARDS[target["key"]].level != 1 for target in state["royal_discard"])
    if key == "skeleton":
        return not state["monster_discard"]
    if key in {"hero4", "hero5", "hero_crest"}:
        if _ai_hero_gain(state, card) > 0 or _ai_sword_hero_gain(state, card) > 0:
            return False
        known = set(state["ai_memory"].get("known_player_hand", []))
        unknown_monsters = [
            target for target in state["hands"]["player"]
            if target["uid"] not in known and CARDS[target["key"]].faction != "royal"
        ]
        return not (len(state["hands"]["ai"]) >= 4 and unknown_monsters)
    if key == "dragonfire" and state["fields"]["player"]:
        best = max(state["fields"]["player"], key=lambda target: _ai_threat_value(state, target))
        return CARDS[best["key"]].level is None and _ai_threat_value(state, best) < 40
    if key == "blacksmith":
        params = _ai_params(state, card)
        chosen = [held for held in state["hands"]["ai"] if held["uid"] in params.get("card_uids", [])]
        if len(chosen) != 2:
            return True
        # 铁匠只在立即赚币，或一次放下两张持续牌时使用。
        # 单张持续牌搭配普通牌会额外暴露 Lv 信息，并制造龙炎的得分目标，不值得冒险。
        places_two_persistent = all(CARDS[target["key"]].persistent for target in chosen)
        earns_coin = _same_mark(chosen)
        return not earns_coin and not places_two_persistent
    return False


def _drive_ai(state: dict) -> None:
    guard = 0
    while state["status"] == "playing" and not state.get("pending") and state["current_player"] == "ai":
        guard += 1
        if guard > 12:
            raise RuntimeError("AI turn exceeded safety bound")
        if state["phase"] != "main":
            break
        # 横置能力不消耗行动点，必须在“行动点耗尽并结束回合”之前检查。
        if _ai_activate_persistent(state):
            continue
        if state["action_points"] <= 0:
            _end_turn(state, "ai", force=True)
            continue
        if _ai_should_take_tavern(state):
            source = _ai_draw_source(state)
            if source.startswith("tavern:") and _draw_card(state, "ai", source):
                state["action_points"] -= 1
                if state.get(ACTION_EVENTS_KEY):
                    state[ACTION_EVENTS_KEY][-1]["action_points"] = state["action_points"]
                continue
        playable = [
            c for c in state["hands"]["ai"]
            if _card_can_play(state, "ai", c) and not _ai_should_hold_card(state, c)
        ]
        # 哥布林只能在比分落后时使用。若先打其他得分牌，可能追平后永久错过
        # 这次制造 2 分差的窗口，因此落后时必须先于普通评分牌结算。
        playable.sort(key=lambda card: _ai_play_priority(state, card), reverse=True)
        if playable:
            card = _ai_preferred_scoring_hero(state, playable) or playable[0]
            # 手里同 key 的候选中，优先打出已公开过的那张（信息已暴露，先打不额外泄露信息）。
            same_key = [c for c in state["hands"]["ai"] if c["key"] == card["key"]]
            if len(same_key) > 1:
                revealed_first = next((c for c in same_key if c.get("_ai_revealed")), None)
                if revealed_first is not None:
                    card = revealed_first
            try:
                _play_card(state, "ai", card["uid"], _ai_params(state, card))
                continue
            except GameError:
                pass
        # 规则：只要还有行动点，就必须尝试用掉——首选抽牌。
        # 只有当所有牌库/酒馆都无法提供牌时（_draw_available 返回 None），才允许结束回合。
        source = _ai_draw_source(state)
        drawn = _draw_available(state, "ai", source)
        if drawn is not None:
            state["action_points"] -= 1
            if state.get(ACTION_EVENTS_KEY):
                state[ACTION_EVENTS_KEY][-1]["action_points"] = state["action_points"]
        else:
            # 抽不到牌（三库全空），行动点作废并结束回合。
            state["action_points"] = 0


def _deal_opening_card(state: dict, player: str, source: str, number: int) -> None:
    pile = state[FACTION_PILES[source]]
    card = pile.pop()
    state["hands"][player].append(card)
    who = "你" if player == "player" else "对手"
    _event(
        state,
        "deal",
        player,
        f"系统给{who}发出第 {number} 张起始手牌",
        source=source,
        card=card if player == "player" else None,
        skippable=False,
    )


def new_game(seed: str | None = None) -> dict:
    seed = seed or secrets.token_hex(12)
    cards = _make_cards()
    tavern: list[dict] = []
    royal: list[dict] = []
    monster: list[dict] = []
    for definition in CARD_DEFINITIONS:
        matching = [card for card in cards if card["key"] == definition.key]
        if definition.tavern_source:
            tavern.append(matching.pop())
        (royal if definition.faction == "royal" else monster).extend(matching)
    rng = random.Random(seed)
    rng.shuffle(tavern)
    rng.shuffle(royal)
    rng.shuffle(monster)
    starting = rng.choice(list(PLAYERS))
    deal_order = (starting, "ai" if starting == "player" else "player")
    state = {
        "schema_version": 3,
        "seed": seed,
        "version": 0,
        "status": "playing",
        "winner": None,
        "result_reason": None,
        "starting_player": starting,
        "current_player": starting,
        "turn_number": 1,
        "phase": "main",
        "action_points": 0,
        "opening_pending": True,
        "coins": {"player": 0, "ai": 0},
        "hands": {"player": [], "ai": []},
        "fields": {"player": [], "ai": []},
        "royal_deck": royal,
        "monster_deck": monster,
        "tavern_deck": tavern,
        "tavern_faceup": [],
        "royal_discard": [],
        "monster_discard": [],
        "pending": None,
        "ai_memory": {"known_player_hand": []},
        "battle_history": [],
        "battle_history_sequence": 0,
        "log": [],
        ACTION_EVENTS_KEY: [],
    }

    for player in deal_order:
        for number in range(1, 4):
            source = rng.choice(tuple(FACTION_PILES))
            _deal_opening_card(state, player, source, number)
    _log(state, "系统已为双方各发出 3 张起始手牌", "gold")

    for number in range(1, 3):
        card = state["tavern_deck"].pop()
        state["tavern_faceup"].append(card)
        _event(
            state,
            "reveal",
            "system",
            f"酒馆翻开第 {number} 张公开牌：{CARDS[card['key']].name}",
            source="tavern",
            card=card,
            skippable=False,
        )
    _log(state, "酒馆已翻开 2 张公开牌", "gold")

    _log(state, f"随机先手结果：{'你' if starting == 'player' else '对手'}先手", "gold")
    _event(
        state,
        "starter",
        "system",
        f"随机先手结果：{'你' if starting == 'player' else '对手'}先手",
        starter=starting,
        skippable=False,
    )
    return state


def _resolve_pending(state: dict, action: dict) -> None:
    pending = state.get("pending")
    if not pending:
        raise GameError("当前没有等待中的响应")
    if pending["type"] == "discard":
        uids = action.get("card_uids") or []
        if len(uids) != pending["count"] or len(set(uids)) != len(uids):
            raise GameError("弃牌数量不正确")
        for uid in uids:
            card = _find_and_pop(state["hands"]["player"], uid)
            destination = f"{CARDS[card['key']].faction}_discard"
            _discard(state, card)
            _event(
                state,
                "discard",
                "player",
                f"你在结束阶段将“{CARDS[card['key']].name}”置入弃牌区",
                card=card,
                source_owner="player",
                destination=destination,
                source_zone="hand",
                destination_zone=destination,
                history_group=f"end-discard-{state['turn_number']}-{card['uid']}",
                record_history=True,
            )
        state["pending"] = None
        state["phase"] = "main"
        for card in state["fields"]["player"]:
            was_tapped = card.get("tapped", False)
            card["tapped"] = False
            if was_tapped:
                _event(state, "tap", "player", f"“{CARDS[card['key']].name}”恢复竖置", card=card, tapped=False)
        _prepare_turn(state, "ai")
    elif pending["type"] == "mage_pick":
        choice = action.get("choice")
        attack_card = pending["attack_card"]
        attacker = pending["attacker"]
        number = pending["number"]
        defender = "player"
        state["pending"] = None
        # 恢复触发时的 history_group，使后续 coin/move 事件与法师 play/effect 归并同一条日志。
        saved_group = pending.get("history_group")
        previous_history_group = state.get("_active_history_group")
        if saved_group is not None:
            state["_active_history_group"] = saved_group
        if choice == "place":
            target_uid = action.get("target_uid")
            if not target_uid or target_uid not in pending["matches"]:
                raise GameError("请选择要放置的 Lv 手牌", details={"required": "target_uid"})
            match = next(
                (c for c in state["hands"][defender]
                 if c["uid"] == target_uid and CARDS[c["key"]].level == number),
                None,
            )
            if match is None:
                raise GameError("目标手牌已不可用")
            chosen = _find_and_pop(state["hands"][defender], target_uid)
            field_slot = len(state["fields"][defender])
            _place_field(state, defender, chosen)
            _move_event(
                state,
                attacker,
                chosen,
                f"你放置「{CARDS[chosen['key']].name}」。",
                source_zone="hand",
                destination_zone="field",
                source_owner=defender,
                destination_owner=defender,
                field_slot=field_slot,
                record_history=True,
            )
            _log(state, f"你放置了 1 张 Lv.{number} 手牌")
        elif choice == "pass":
            _gain_coin(state, attacker, 1, "法师（你放弃放置）", source_card=attack_card)
        else:
            raise GameError("请选择放置或放弃")
        if state["status"] == "playing":
            _finish_played_card(state, attacker, attack_card)
        if state["status"] == "playing":
            _trigger_demon_after_play(state, attacker, attack_card)
        if saved_group is not None:
            if previous_history_group is None:
                state.pop("_active_history_group", None)
            else:
                state["_active_history_group"] = previous_history_group
    elif pending["type"] == "guard_trigger":
        choice = action.get("choice")
        attack_card = pending["attack_card"]
        attacker = pending["attacker"]
        state["pending"] = None
        saved_group = pending.get("history_group")
        previous_history_group = state.get("_active_history_group")
        if saved_group is not None:
            state["_active_history_group"] = saved_group
        if choice == "use":
            guard = _find_and_pop(state["hands"]["player"], pending["guard_uid"])
            message = "你使用卫兵，使对手的攻击无效"
            _log(state, message, "royal")
            _event(state, "trigger", "player", message, card=guard)
            _discard(state, guard)
            guard_destination = f"{CARDS[guard['key']].faction}_discard"
            _event(
                state,
                "discard",
                "player",
                "你将“卫兵”置入弃牌区",
                card=guard,
                source_owner="player",
                destination=guard_destination,
                source_zone="hand",
                destination_zone=guard_destination,
            )
            attack_card.pop("_visual_slot", None)
            field_slot = len(state["fields"][attacker])
            _place_field(state, attacker, attack_card)
            _move_event(
                state,
                "player",
                attack_card,
                f"攻击无效，“{CARDS[attack_card['key']].name}”留在对手场上",
                source_zone="resolution",
                destination_zone="field",
                destination_owner=attacker,
                field_slot=field_slot,
            )
            _draw_available(state, "player", "royal", history_group=state.get("_active_history_group"))
            _refund_guarded_attack_action(state, attacker, attack_card)
        elif choice == "pass":
            _resolve_attack_effect(state, attacker, attack_card, pending["effect"])
            _finish_played_card(state, attacker, attack_card)
        else:
            raise GameError("请选择使用或放弃卫兵")
        if state["status"] == "playing":
            _trigger_demon_after_play(state, attacker, attack_card)
        if saved_group is not None:
            if previous_history_group is None:
                state.pop("_active_history_group", None)
            else:
                state["_active_history_group"] = previous_history_group
    else:
        raise GameError("未知响应类型")


def apply_action(state: dict, action: dict) -> dict:
    next_state = copy.deepcopy(state)
    next_state[ACTION_EVENTS_KEY] = []
    if next_state["status"] != "playing":
        raise GameError("对局已经结束")
    action_type = action.get("type")
    if next_state.get("opening_pending"):
        if action_type != "opening_complete":
            raise GameError("请等待开局演出完成")
        next_state["opening_pending"] = False
        next_state["phase"] = "prepare"
        next_state["action_points"] = 0
        opening_actor = next_state["starting_player"]
        prepare_message = f"{'你的' if opening_actor == 'player' else '对手的'}准备阶段"
        _event(
            next_state,
            "phase",
            opening_actor,
            prepare_message,
            phase="prepare",
            history_group=f"turn-divider-{next_state['turn_number']}",
            record_history=True,
            skippable=False,
        )
        next_state["phase"] = "main"
        next_state["action_points"] = 1
        main_message = f"{'你的' if opening_actor == 'player' else '对手的'}首回合主要阶段开始，获得 1 个行动点"
        _log(next_state, main_message, "gold")
        _event(next_state, "phase", opening_actor, main_message, phase="main", skippable=False)
    elif next_state.get("pending"):
        if action_type != "resolve":
            raise GameError("请先完成当前响应")
        _resolve_pending(next_state, action)
    elif next_state["current_player"] != "player":
        raise GameError("现在是对手行动")
    elif next_state["phase"] == "main":
        if action_type == "draw":
            if next_state["action_points"] <= 0:
                raise GameError("行动点不足")
            next_state["action_points"] -= 1
            _draw_card(next_state, "player", action.get("source", ""))
        elif action_type == "play":
            _play_card(next_state, "player", action.get("card_uid", ""), action.get("params") or {})
        elif action_type == "activate":
            _activate(next_state, "player", action.get("card_uid", ""), action.get("params") or {})
        elif action_type == "end_turn":
            _end_turn(next_state, "player", force=bool(action.get("confirmed")))
        else:
            raise GameError("未知操作")
    else:
        raise GameError("当前阶段不能执行该操作")
    next_state["version"] += 1
    _drive_ai(next_state)
    return next_state


def _masked_hand(cards: list[dict]) -> list[dict]:
    return [_masked_card(card) for card in cards]


def public_state(state: dict) -> dict[str, Any]:
    result = {
        key: copy.deepcopy(value)
        for key, value in state.items()
        if key not in {"seed", "hands", "royal_deck", "monster_deck", "tavern_deck", "ai_memory", ACTION_EVENTS_KEY}
    }
    # 兼容旧对局：battle_history / log 里如果还残留"电脑"字样（旧 state 保存的），统一改成"对手"
    for entry in result.get("log", []):
        entry["message"] = entry.get("message", "").replace("电脑", "对手")
    for entry in result.get("battle_history", []):
        entry["message"] = entry.get("message", "").replace("电脑", "对手")
    # 兼容旧对局 / 补齐分割线：battle_history 里如果 turn N 缺失 phase-prepare 分割线，
    # 由第一条 turn=N 的事件位置合成一条。starting_player 的首回合不合成（首回合无准备阶段）。
    history = result.get("battle_history") or []
    if history:
        existing_turns = {
            entry.get("turn_number") for entry in history
            if entry.get("type") == "phase" and entry.get("phase") == "prepare"
        }
        starting = state.get("starting_player")
        synthesized = []
        prev_turn = None
        for entry in history:
            turn = entry.get("turn_number")
            if (
                turn is not None
                and turn != prev_turn
                and turn not in existing_turns
                # 首回合的先手方没有准备阶段——只有真正跨过回合切换才补分割线。
                and not (turn == 1 and entry.get("actor") == starting)
            ):
                actor = "player" if (turn % 2 == 1) ^ (starting == "ai") else "ai"
                synthesized.append({
                    "id": 0,
                    "type": "phase",
                    "phase": "prepare",
                    "actor": actor,
                    "message": f"{'你的' if actor == 'player' else '对手的'}准备阶段",
                    "turn_number": turn,
                    "history_group": f"turn-divider-{turn}",
                    "history_id": f"synth-turn-{turn}",
                    "skippable": False,
                })
                existing_turns.add(turn)
            synthesized.append(entry)
            prev_turn = turn
        result["battle_history"] = synthesized
    result["hands"] = {
        "player": [card_public(card) for card in state["hands"]["player"]],
        "ai": _masked_hand(state["hands"]["ai"]),
    }
    result["fields"] = {
        player: [card_public(card) for card in state["fields"][player]] for player in PLAYERS
    }
    result["tavern_faceup"] = [card_public(card) for card in state["tavern_faceup"]]
    result["royal_discard_top"] = card_public(state["royal_discard"][-1]) if state["royal_discard"] else None
    result["monster_discard_top"] = card_public(state["monster_discard"][-1]) if state["monster_discard"] else None
    result["royal_discard"] = [card_public(card) for card in state["royal_discard"]]
    result["monster_discard"] = [card_public(card) for card in state["monster_discard"]]
    result["counts"] = {
        "royal_deck": len(state["royal_deck"]),
        "monster_deck": len(state["monster_deck"]),
        "tavern_deck": len(state["tavern_deck"]),
        "royal_discard": len(state["royal_discard"]),
        "monster_discard": len(state["monster_discard"]),
    }
    if result.get("pending") and result["pending"].get("type") == "guard_trigger":
        pending = result["pending"]
        result["pending"] = {
            "type": pending["type"],
            "prompt": pending["prompt"],
            "attack_card": card_public(pending["attack_card"]),
            "options": pending["options"],
        }
    elif result.get("pending") and result["pending"].get("type") == "mage_pick":
        pending = result["pending"]
        result["pending"] = {
            "type": pending["type"],
            "prompt": pending["prompt"],
            "attack_card": card_public(pending["attack_card"]),
            "number": pending["number"],
            "matches": pending["matches"],
            "options": pending["options"],
        }
    result["card_names"] = CARD_NAMES
    playable = {
        card["uid"]: _card_can_play(state, "player", card)
        for card in state["hands"]["player"]
    }
    targets: dict[str, list[str]] = {}
    alternative_targets: dict[str, list[str]] = {}
    for card in state["hands"]["player"]:
        if card["key"] in {"hero4", "hero5", "hero_crest"}:
            targets[card["uid"]] = (
                [target["uid"] for target in state["hands"]["ai"] if CARDS[target["key"]].faction != "royal"]
                if _has_field_space(state, "ai")
                else []
            )
            alternative_targets[card["uid"]] = (
                [target["uid"] for target in state["fields"]["ai"]]
                if _has_hero_sword_option(state, "player")
                else []
            )
        elif card["key"] == "dragonfire":
            targets[card["uid"]] = [target["uid"] for target in state["fields"]["ai"]]
        elif card["key"] == "blacksmith":
            targets[card["uid"]] = [target["uid"] for target in state["hands"]["player"] if target["uid"] != card["uid"]]
    monk_playable: dict[str, bool] = {}
    monk_targets: dict[str, list[str]] = {}
    monk_alternative_targets: dict[str, list[str]] = {}
    monk = next((card for card in state["hands"]["player"] if card["key"] == "monk"), None)
    if monk:
        for card in state["royal_discard"]:
            if CARDS[card["key"]].level == 1:
                continue
            monk_playable[card["uid"]] = _monk_card_can_play(state, "player", monk["uid"], card)
            if card["key"] in {"hero4", "hero5", "hero_crest"}:
                monk_targets[card["uid"]] = (
                    [target["uid"] for target in state["hands"]["ai"] if CARDS[target["key"]].faction != "royal"]
                    if _has_field_space(state, "ai")
                    else []
                )
                monk_alternative_targets[card["uid"]] = (
                    [target["uid"] for target in state["fields"]["ai"]]
                    if _has_hero_sword_option(state, "player")
                    else []
                )
    result["legal"] = {
        "playable": playable,
        "targets": targets,
        "alternative_targets": alternative_targets,
        "monk_playable": monk_playable,
        "monk_targets": monk_targets,
        "monk_alternative_targets": monk_alternative_targets,
        "activatable": [
            card["uid"] for card in state["fields"]["player"]
            if not card.get("tapped") and (
                (card["key"] == "king" and any(c["key"] == "hero4" for c in state["royal_discard"]))
                or (card["key"] == "fire_dragon" and any(c["key"] == "dragonfire" for c in state["monster_discard"]))
            )
        ],
    }
    return result
