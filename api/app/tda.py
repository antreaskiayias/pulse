import numpy as np

def build_point_cloud(prices: list[float], quantities: list[float]) -> np.ndarray:
    """0-skeleton: each trade becomes a point (price_delta, log_quantity).
    price_delta is relative to the window mean so the cloud is centered,
    which makes a fixed epsilon threshold meaningful across price regimes."""
    prices = np.array(prices)
    quantities = np.array(quantities)
    price_delta = prices - prices.mean()
    log_qty = np.log1p(quantities)
    return np.column_stack([price_delta, log_qty])


def build_vietoris_rips_edges(points: np.ndarray, epsilon: float) -> list[tuple[int, int]]:
    """1-skeleton: connect point i and j iff their distance <= epsilon."""
    n = len(points)
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            if np.linalg.norm(points[i] - points[j]) <= epsilon:
                edges.append((i, j))
    return edges


def betti_numbers(n_points: int, edges: list[tuple[int, int]]) -> tuple[int, int]:
    """Betti-0: connected components (union-find).
    Betti-1: cycle rank = |E| - |V| + Betti-0, valid for a graph's 1-skeleton."""
    parent = list(range(n_points))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i, j in edges:
        union(i, j)

    betti_0 = len({find(i) for i in range(n_points)})
    betti_1 = len(edges) - n_points + betti_0
    return betti_0, betti_1
