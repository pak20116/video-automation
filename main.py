import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Video Automation Pipeline — convert a text script into an MP4 video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py scripts/my_script.txt
  python main.py scripts/my_script.txt --start-step 4
  python main.py scripts/my_script.txt --start-step 7
        """,
    )
    parser.add_argument(
        "script",
        help="Path to the input script .txt file",
    )
    parser.add_argument(
        "--start-step",
        type=int,
        default=1,
        choices=range(1, 8),
        metavar="N",
        help="Start from step N (1-7). Use to resume after a failure. Default: 1",
    )

    args = parser.parse_args()

    script_path = Path(args.script).resolve()
    if not script_path.exists():
        print(f"ERROR: Script file not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    # Import here so API key validation in settings.py only runs after args are parsed
    from pipeline.orchestrator import run_pipeline

    try:
        state = run_pipeline(
            script_path=str(script_path),
            start_step=args.start_step,
        )
        print(f"\nSuccess! Video saved to:\n  {state.output_video_path}")
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\nPipeline failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
