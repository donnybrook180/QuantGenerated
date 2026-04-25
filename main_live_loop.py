import sys
from quant_system.live.loop_app import main as run_live_loop_main


def main() -> int:
    return run_live_loop_main(sys.argv[1:])



if __name__ == "__main__":
    raise SystemExit(main())
