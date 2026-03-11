from __future__ import annotations

from pathlib import Path

from graph.skill_selector import SkillSelector


def _write_skill(root: Path, name: str, description: str, body: str) -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_skill_selector_picks_crypto_skills_for_bsc_meme_prompt(tmp_path: Path):
    _write_skill(
        tmp_path,
        "crypto-market-rank",
        "Trending token rankings, meme rankings, market trends, and Binance Alpha discovery.",
        "# Crypto Market Rank\nUse for trending tokens, market leaders, and meme ranks on BSC.",
    )
    _write_skill(
        tmp_path,
        "meme-rush",
        "Meme token discovery for BSC and launchpads, including trending meme narratives.",
        "# Meme Rush\nUse for BSC meme tokens, launchpads, and fast meme trading.",
    )
    _write_skill(
        tmp_path,
        "session-logs",
        "Search and analyze old session logs.",
        "# Session Logs\nUse for previous conversation analysis only.",
    )

    selector = SkillSelector()
    selected = selector.select(
        base_dir=tmp_path,
        message="which meme token is trending on BSC?",
        history=[],
    )

    assert [item.name for item in selected[:2]] == [
        "crypto-market-rank",
        "meme-rush",
    ]


def test_skill_selector_is_deterministic_for_same_prompt(tmp_path: Path):
    _write_skill(
        tmp_path,
        "meme-rush",
        "Meme token discovery for BSC and launchpads, including trending meme narratives.",
        "# Meme Rush\nUse for BSC meme tokens, launchpads, and fast meme trading.",
    )

    selector = SkillSelector()
    first = selector.select(
        base_dir=tmp_path,
        message="which meme token is trending on BSC?",
        history=[{"role": "user", "content": "show top meme ranks"}],
    )
    second = selector.select(
        base_dir=tmp_path,
        message="which meme token is trending on BSC?",
        history=[{"role": "user", "content": "show top meme ranks"}],
    )

    assert first == second


def test_skill_selector_prioritizes_explicitly_named_skills(tmp_path: Path):
    _write_skill(
        tmp_path,
        "crypto-market-rank",
        "Trending token rankings, meme rankings, market trends, and Binance Alpha discovery.",
        "# Crypto Market Rank\nUse for trending tokens, market leaders, and meme ranks on BSC.",
    )
    _write_skill(
        tmp_path,
        "session-logs",
        "Search and analyze old session logs.",
        "# Session Logs\nUse for previous conversation analysis only.",
    )

    selector = SkillSelector()
    selected = selector.select(
        base_dir=tmp_path,
        message="use crypto-market-rank to check BSC meme leaders",
        history=[],
    )

    assert selected
    assert selected[0].name == "crypto-market-rank"
    assert "explicitly named" in selected[0].reason
