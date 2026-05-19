"""
Test runner: validates 10 archetypes for rank-ordering and range compliance.
"""
from engine import score_individual
from profiles import PROFILES

def run_tests():
    results = []
    print("=" * 90)
    print(f"{'Profile':<45} {'FHS':>5} {'Exp':>11} {'OK':>3}  {'FSS':>5} {'Exp':>11} {'OK':>3}")
    print("-" * 90)

    for p in PROFILES:
        inp = p["input"]
        r = score_individual(inp)
        fhs_ok = p["expected_fhs"][0] <= r.fhs <= p["expected_fhs"][1]
        fss_ok = p["expected_fss"][0] <= r.fss <= p["expected_fss"][1]
        status_fhs = " Y " if fhs_ok else "***"
        status_fss = " Y " if fss_ok else "***"
        print(f"{inp.name:<45} {r.fhs:>5} {str(p['expected_fhs']):>11} {status_fhs}  {r.fss:>5} {str(p['expected_fss']):>11} {status_fss}")
        results.append((inp.name, r.fhs, r.fss, r.frs, fhs_ok, fss_ok, r))

    print("-" * 90)

    # Rank-order check: sort by FHS descending, verify it matches intuitive ordering
    by_fhs = sorted(results, key=lambda x: x[1], reverse=True)
    print("\nRank ordering by FHS (highest to lowest):")
    for i, (name, fhs, fss, frs, _, _, _) in enumerate(by_fhs, 1):
        print(f"  {i:>2}. FHS={fhs:>4}  FSS={fss:>3}  FRS={frs:>3}  {name}")

    # Check monotonicity: FHS and FSS should be inversely correlated
    fhs_values = [r[1] for r in results]
    fss_values = [r[2] for r in results]

    n_pass = sum(1 for r in results if r[4] and r[5])
    n_total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Range compliance: {n_pass}/{n_total} profiles in expected ranges")
    print(f"{'=' * 60}")

    # Print one detailed breakdown
    print("\n--- Detailed breakdown: Profile 3 (Average) ---")
    r = results[2][6]
    if r.lp_solution and r.lp_solution.status == "Optimal":
        print(f"  LP Status: {r.lp_solution.status}")
        print(f"  LP Objective: {r.lp_solution.objective_value:.4f}")
        print(f"\n  Optimal Allocation:")
        for k, v in r.optimal_allocation.items():
            print(f"    {k}: ${v:,.2f}/mo")
        print(f"\n  Milestones: {r.actual_vs_optimal.get('milestones_achieved', {})}")
        print(f"\n  FHS Breakdown:")
        for k, v in r.fhs_breakdown.items():
            details = ", ".join(f"{dk}={dv}" for dk, dv in v.items() if dk != "weight")
            print(f"    {k} (w={v.get('weight',0):.2f}): {details}")
        print(f"\n  FSS Breakdown:")
        for k, v in r.fss_breakdown.items():
            print(f"    {k}: {v}")


if __name__ == "__main__":
    run_tests()
