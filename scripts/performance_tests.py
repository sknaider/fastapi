#!/usr/bin/env python
"""
Performance regression testing framework for FastAPI.

Runs performance benchmarks and compares against baseline.
"""

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List

try:
    import httpx
except ImportError:
    print("httpx is required. Install with: pip install httpx")
    exit(1)


class PerformanceBenchmark:
    """Performance benchmark runner."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = []

    def benchmark_endpoint(
        self,
        method: str,
        path: str,
        iterations: int = 100,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Benchmark an endpoint.

        Args:
            method: HTTP method
            path: Endpoint path
            iterations: Number of iterations
            **kwargs: Additional arguments for httpx.request

        Returns:
            Benchmark results
        """
        url = f"{self.base_url}{path}"
        durations = []
        errors = 0

        print(f"Benchmarking {method} {path} ({iterations} iterations)...")

        for i in range(iterations):
            start = time.time()
            try:
                with httpx.Client() as client:
                    response = client.request(method, url, **kwargs)
                    response.raise_for_status()
                duration = (time.time() - start) * 1000  # Convert to ms
                durations.append(duration)
            except Exception as e:
                errors += 1
                print(f"  Error in iteration {i + 1}: {e}")

        if not durations:
            return {
                "endpoint": f"{method} {path}",
                "error": "All requests failed",
            }

        # Calculate statistics
        result = {
            "endpoint": f"{method} {path}",
            "iterations": iterations,
            "errors": errors,
            "success_rate": (iterations - errors) / iterations * 100,
            "min_ms": min(durations),
            "max_ms": max(durations),
            "mean_ms": statistics.mean(durations),
            "median_ms": statistics.median(durations),
            "p95_ms": self._percentile(durations, 95),
            "p99_ms": self._percentile(durations, 99),
            "stdev_ms": statistics.stdev(durations) if len(durations) > 1 else 0,
        }

        self.results.append(result)
        self._print_result(result)
        return result

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile."""
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def _print_result(self, result: Dict[str, Any]) -> None:
        """Print benchmark result."""
        print(f"\n  Results for {result['endpoint']}:")
        print(f"    Success rate: {result['success_rate']:.1f}%")
        print(f"    Mean: {result['mean_ms']:.2f}ms")
        print(f"    Median: {result['median_ms']:.2f}ms")
        print(f"    Min: {result['min_ms']:.2f}ms")
        print(f"    Max: {result['max_ms']:.2f}ms")
        print(f"    P95: {result['p95_ms']:.2f}ms")
        print(f"    P99: {result['p99_ms']:.2f}ms")
        print(f"    StdDev: {result['stdev_ms']:.2f}ms")

    def save_results(self, output_path: Path) -> None:
        """Save results to JSON file."""
        with open(output_path, "w") as f:
            json.dump(
                {
                    "timestamp": time.time(),
                    "base_url": self.base_url,
                    "results": self.results,
                },
                f,
                indent=2,
            )
        print(f"\n✅ Results saved to {output_path}")

    def compare_with_baseline(
        self, baseline_path: Path, threshold_percent: float = 10.0
    ) -> bool:
        """
        Compare results with baseline.

        Args:
            baseline_path: Path to baseline results
            threshold_percent: Acceptable degradation percentage

        Returns:
            True if within threshold, False otherwise
        """
        if not baseline_path.exists():
            print(f"⚠️  No baseline found at {baseline_path}")
            return True

        with open(baseline_path) as f:
            baseline_data = json.load(f)

        baseline_results = {r["endpoint"]: r for r in baseline_data["results"]}

        regressions = []
        improvements = []

        print(f"\n📊 Comparing with baseline ({baseline_path}):")
        print(f"   Threshold: {threshold_percent}% degradation")

        for result in self.results:
            endpoint = result["endpoint"]
            if endpoint not in baseline_results:
                print(f"\n  ℹ️  {endpoint}: New endpoint (no baseline)")
                continue

            baseline = baseline_results[endpoint]

            # Compare mean duration
            current_mean = result["mean_ms"]
            baseline_mean = baseline["mean_ms"]
            diff_percent = (
                (current_mean - baseline_mean) / baseline_mean * 100
                if baseline_mean > 0
                else 0
            )

            status = "✅"
            if diff_percent > threshold_percent:
                status = "❌"
                regressions.append((endpoint, diff_percent))
            elif diff_percent < -5:  # Improvement of more than 5%
                status = "🚀"
                improvements.append((endpoint, diff_percent))

            print(f"\n  {status} {endpoint}:")
            print(f"     Baseline: {baseline_mean:.2f}ms")
            print(f"     Current:  {current_mean:.2f}ms")
            print(f"     Change:   {diff_percent:+.1f}%")

        # Summary
        print("\n" + "=" * 60)
        if regressions:
            print(f"❌ PERFORMANCE REGRESSION DETECTED!")
            print(f"   {len(regressions)} endpoint(s) degraded:")
            for endpoint, diff in regressions:
                print(f"   - {endpoint}: {diff:+.1f}%")
            return False
        elif improvements:
            print(f"✅ Performance within threshold")
            print(f"🚀 {len(improvements)} endpoint(s) improved:")
            for endpoint, diff in improvements:
                print(f"   - {endpoint}: {diff:+.1f}%")
        else:
            print(f"✅ Performance within threshold (no significant changes)")

        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="FastAPI Performance Benchmarks")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the API",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of iterations per endpoint",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("performance-results.json"),
        help="Output file for results",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("performance-baseline.json"),
        help="Baseline file for comparison",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        help="Acceptable degradation percentage",
    )
    parser.add_argument(
        "--set-baseline",
        action="store_true",
        help="Set current results as baseline",
    )

    args = parser.parse_args()

    # Create benchmark runner
    benchmark = PerformanceBenchmark(base_url=args.base_url)

    # Define endpoints to benchmark
    # These are example endpoints - customize for your API
    endpoints = [
        ("GET", "/"),
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
    ]

    # Run benchmarks
    for method, path in endpoints:
        benchmark.benchmark_endpoint(method, path, iterations=args.iterations)

    # Save results
    benchmark.save_results(args.output)

    # Set as baseline if requested
    if args.set_baseline:
        import shutil

        shutil.copy(args.output, args.baseline)
        print(f"✅ Baseline updated: {args.baseline}")
        return 0

    # Compare with baseline
    if not benchmark.compare_with_baseline(args.baseline, args.threshold):
        print("\n❌ Performance regression detected!")
        return 1

    print("\n✅ All performance tests passed!")
    return 0


if __name__ == "__main__":
    exit(main())
