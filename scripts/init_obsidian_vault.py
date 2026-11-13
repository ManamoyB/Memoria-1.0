"""Create the recommended MemoriaOS folder structure in an Obsidian vault."""

from app.obsidian.config import ObsidianConfig


def main() -> None:
    config = ObsidianConfig.from_env()
    root = config.ensure_vault()
    print(f"MemoriaOS vault structure ready: {root}")
    for folder in config.folders:
        print(f"  - {folder}")


if __name__ == "__main__":
    main()
