import os
import sys
import time
import signal
import subprocess
from load_generator import run_test, print_result

STRATEGIES = ["lazy", "write-through", "write-back"]
PROFILES = ["read-heavy", "balanced", "write-heavy"]

REQUESTS_PER_TEST = 1000


def start_app(strategy):
    env = os.environ.copy()
    env["CACHE_STRATEGY"] = strategy

    process = subprocess.Popen(
      [sys.executable, "app.py"],
      env=env,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      text=True,
  )

    time.sleep(2)
    return process


def stop_app(process):
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main():
    all_results = []

    for strategy in STRATEGIES:
        print("\n" + "#" * 80)
        print(f"START STRATEGY: {strategy}")
        print("#" * 80)

        app_process = start_app(strategy)

        try:
            for profile in PROFILES:
                result = run_test(
                    profile=profile,
                    requests_count=REQUESTS_PER_TEST,
                    items_count=1000,
                )
                result["strategy"] = strategy
                all_results.append(result)
                print_result(result)

        finally:
            stop_app(app_process)

    print("\n\nFINAL TABLE")
    print("=" * 130)
    print(
        f"{'strategy':<15} {'profile':<12} {'rps':<10} {'avg ms':<10} "
        f"{'db reads':<10} {'db writes':<10} {'hit rate':<10} {'wb pending':<10}"
    )
    print("=" * 130)

    for r in all_results:
        print(
            f"{r['strategy']:<15} {r['profile']:<12} "
            f"{r['throughput_req_sec']:<10} {r['avg_latency_ms']:<10} "
            f"{r['db_reads']:<10} {r['db_writes']:<10} "
            f"{r['cache_hit_rate']:<10} {r['write_back_pending']:<10}"
        )


if __name__ == "__main__":
    main()
