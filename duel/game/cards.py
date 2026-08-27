from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CardDefinition:
    key: str
    name: str
    faction: str
    copies: int
    kind: str
    level: int | None
    crests: tuple[str, ...]
    effect: str
    art_index: int
    persistent: bool = False
    tavern_source: bool = False


CARD_DEFINITIONS = (
    CardDefinition("blacksmith", "铁匠", "royal", 4, "normal", 0, (), "将 2 张手牌放置于你的场上。若因此放置的牌 Lv 或纹章相同，你获得 1 枚金币。", 0, tavern_source=True),
    CardDefinition("monk", "僧侣", "royal", 4, "normal", 1, (), "从皇室弃牌区选择 1 张 Lv.1 以外的牌，不消耗行动点打出，或将其加入手牌。", 1, tavern_source=True),
    CardDefinition("mage", "法师", "royal", 4, "attack", 2, (), "宣言 1、2、3、4 中的数字。对手放置该等级的 1 张手牌，否则你获得 1 枚金币。", 2, tavern_source=True),
    CardDefinition("guard", "卫兵", "royal", 4, "trigger", 3, (), "当你被攻击牌指定时，使攻击无效、将攻击牌放置到打出者场上，然后抽 1 张牌。若该牌消耗了行动点，将其返还。", 3, tavern_source=True),
    CardDefinition("hero4", "勇者", "royal", 4, "attack", 4, (), "选择对手 1 张非皇室手牌并放置到对手场上。若本牌 Lv 更高，你获得 1 枚金币。", 4, tavern_source=True),
    CardDefinition("hero5", "勇者", "royal", 1, "attack", 5, (), "选择对手 1 张非皇室手牌并放置到对手场上。若本牌 Lv 更高，你获得 1 枚金币。", 5),
    CardDefinition("hero_crest", "勇者", "royal", 1, "attack", None, ("royal",), "选择对手 1 张非皇室手牌并放置。若目标带有 Lv 或魔物纹章，你获得 1 枚金币。", 6),
    CardDefinition("king", "国王", "royal", 1, "persistent", None, ("royal",), "横置：将弃牌区中 1 张 Lv.4 的勇者加入手牌。", 7, persistent=True),
    CardDefinition("princess", "公主", "royal", 1, "persistent", None, ("royal",), "在你的准备阶段，你获得 1 枚金币。", 8, persistent=True),
    CardDefinition("holy_sword", "圣剑", "royal", 1, "persistent", None, ("royal",), "打出勇者时可横置，改为丢弃对手场上的牌；等级更高则获得 1 枚金币。", 9, persistent=True),
    CardDefinition("holy_grail", "圣杯", "royal", 1, "persistent", None, ("royal",), "准备阶段若只差 1 枚金币即可获胜，则直接获胜。", 10, persistent=True),
    CardDefinition("bat", "蝙蝠", "monster", 4, "attack", 1, (), "秘密查看对手全部手牌，之后令其场上的牌全部回到手牌。", 11, tavern_source=True),
    CardDefinition("skeleton", "白骨", "monster", 4, "normal", 2, (), "从魔物弃牌区选择 1 张牌放置到你的场上。", 12, tavern_source=True),
    CardDefinition("witch", "女巫", "monster", 4, "attack", 3, (), "宣言 1 张牌名。若对手手牌或场上拥有该牌，其交付其中 1 张到你的手牌。", 13, tavern_source=True),
    CardDefinition("goblin", "哥布林", "monster", 4, "attack", 4, (), "指定金币更多的对手，该对手向你交付 1 枚金币。", 14, tavern_source=True),
    CardDefinition("dragonfire", "龙炎", "monster", 4, "attack", None, ("flame",), "丢弃对手场上的 1 张牌。若该牌带有 Lv，你获得 1 枚金币。", 15, tavern_source=True),
    CardDefinition("dragon_egg", "龙蛋", "monster", 1, "normal", None, ("flame",), "选择龙炎或火龙：优先从魔物弃牌区加入手牌；没有则从魔物牌库加入手牌。", 16),
    CardDefinition("fire_dragon", "火龙", "monster", 1, "persistent", None, ("monster", "flame"), "横置：将弃牌区的 1 张龙炎不消耗行动点打出，或将其加入手牌。", 17, persistent=True),
    CardDefinition("demon_king", "魔王", "monster", 1, "persistent", None, ("monster",), "打出带 Lv 的魔物牌后可横置，本方获得 1 枚金币。", 18, persistent=True),
)

CARDS = {card.key: card for card in CARD_DEFINITIONS}
CARD_NAMES = sorted({card.name for card in CARD_DEFINITIONS})


def card_public(card: dict) -> dict:
    definition = CARDS[card["key"]]
    public = asdict(definition)
    public["crests"] = list(definition.crests)
    public["crest"] = definition.crests[0] if definition.crests else None
    return {"uid": card["uid"], **public, "tapped": bool(card.get("tapped"))}


def card_catalog() -> list[dict]:
    """返回与对局完全同源的公开卡牌图鉴。"""

    return [card_public({"uid": f"catalog-{definition.key}", "key": definition.key}) for definition in CARD_DEFINITIONS]
