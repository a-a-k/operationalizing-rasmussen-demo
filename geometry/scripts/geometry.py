from __future__ import annotations

import math
from collections.abc import Sequence

Vector = tuple[float, ...]
Basis = tuple[Vector, ...]

CPU_BASIS: Basis = (
    (1 / math.sqrt(12), 1 / math.sqrt(12), 1 / math.sqrt(12), -math.sqrt(3 / 4)),
    (math.sqrt(2 / 3), -1 / math.sqrt(6), -1 / math.sqrt(6), 0.0),
    (0.0, 1 / math.sqrt(2), -1 / math.sqrt(2), 0.0),
)
RAM_BASIS: Basis = ((1 / math.sqrt(2), -1 / math.sqrt(2)),)


def positive(values: Sequence[float]) -> Vector:
    result = tuple(float(v) for v in values)
    if len(result) < 2 or any(not math.isfinite(v) or v <= 0 for v in result):
        raise ValueError('a composition requires at least two positive finite parts')
    return result


def close(values: Sequence[float]) -> Vector:
    values = positive(values)
    scaled = tuple(v / max(values) for v in values)
    total = math.fsum(scaled)
    return positive(tuple(v / total for v in scaled))


def clr(values: Sequence[float]) -> Vector:
    logs = tuple(math.log(v) for v in positive(values))
    centre = math.fsum(logs) / len(logs)
    return tuple(v - centre for v in logs)


def difference(left: Sequence[float], right: Sequence[float]) -> Vector:
    if len(left) != len(right):
        raise ValueError('vector dimensions differ')
    return tuple(a - b for a, b in zip(left, right))


def dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError('vector dimensions differ')
    return math.fsum(a * b for a, b in zip(left, right))


def norm(vector: Sequence[float]) -> float:
    return math.hypot(*vector)


def distance(left: Sequence[float], right: Sequence[float]) -> float:
    return norm(difference(left, right))


def aitchison(left: Sequence[float], right: Sequence[float]) -> float:
    return distance(clr(left), clr(right))


def share_euclidean(left: Sequence[float], right: Sequence[float]) -> float:
    return distance(close(left), close(right))


def validate_basis(basis: Basis) -> None:
    if not basis or any(len(row) != len(basis) + 1 for row in basis):
        raise ValueError('a full ILR basis requires D-1 rows of length D')
    if any(not all(math.isfinite(v) for v in row) or abs(math.fsum(row)) > 1e-12 for row in basis):
        raise ValueError('basis rows must be finite and orthogonal to the constant vector')
    for i, a in enumerate(basis):
        for j, b in enumerate(basis):
            if abs(dot(a, b) - int(i == j)) > 1e-12:
                raise ValueError('basis rows must be orthonormal')


def ilr(values: Sequence[float], basis: Basis) -> Vector:
    validate_basis(basis)
    logs = clr(values)
    if len(logs) != len(basis[0]):
        raise ValueError('composition and basis dimensions differ')
    return tuple(dot(logs, row) for row in basis)


def inverse_ilr(coordinates: Sequence[float], basis: Basis) -> Vector:
    validate_basis(basis)
    if len(coordinates) != len(basis) or any(not math.isfinite(v) for v in coordinates):
        raise ValueError('invalid ILR coordinates')
    logs = tuple(math.fsum(c * row[i] for c, row in zip(coordinates, basis))
                 for i in range(len(basis[0])))
    maximum = max(logs)
    return close(tuple(math.exp(v - maximum) for v in logs))


def perturb(values: Sequence[float], factors: Sequence[float]) -> Vector:
    values, factors = positive(values), positive(factors)
    if len(values) != len(factors):
        raise ValueError('perturbation dimensions differ')
    return close(tuple(a * b for a, b in zip(values, factors)))


def rotate_basis(basis: Basis, degrees: float) -> Basis:
    validate_basis(basis)
    if len(basis) < 2 or not math.isfinite(degrees):
        raise ValueError('rotation needs at least two coordinates and a finite angle')
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    first = tuple(c * a - s * b for a, b in zip(basis[0], basis[1]))
    second = tuple(s * a + c * b for a, b in zip(basis[0], basis[1]))
    result = (first, second, *basis[2:])
    validate_basis(result)
    return result


def angle(left: Sequence[float], right: Sequence[float]) -> float | None:
    a, b = norm(left), norm(right)
    if a <= 1e-12 or b <= 1e-12:
        return None
    u, v = tuple(x / a for x in left), tuple(x / b for x in right)
    return 2 * math.atan2(distance(u, v), norm(tuple(x + y for x, y in zip(u, v))))


def product(cpu: Sequence[float], ram: Sequence[float], weights: dict[str, float]) -> Vector:
    if set(weights) != {'cpu', 'ram'} or any(not math.isfinite(v) or v <= 0 for v in weights.values()):
        raise ValueError('product weights must be positive finite values for CPU and RAM')
    return (*tuple(math.sqrt(weights['cpu']) * v for v in cpu),
            *tuple(math.sqrt(weights['ram']) * v for v in ram))
