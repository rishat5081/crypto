from __future__ import annotations

import math
from typing import List, Sequence


class StandardScaler:
    def __init__(self) -> None:
        self.mean: List[float] = []
        self.std: List[float] = []

    def fit(self, vectors: Sequence[Sequence[float]]) -> None:
        if not vectors:
            raise ValueError("Cannot fit scaler on empty vectors")
        dim = len(vectors[0])
        n = len(vectors)
        self.mean = [0.0] * dim
        self.std = [0.0] * dim
        for row in vectors:
            for i, value in enumerate(row):
                self.mean[i] += value
        self.mean = [m / n for m in self.mean]
        for row in vectors:
            for i, value in enumerate(row):
                diff = value - self.mean[i]
                self.std[i] += diff * diff
        self.std = [math.sqrt(v / max(1, n - 1)) if v > 0 else 1.0 for v in self.std]

    def transform(self, vectors: Sequence[Sequence[float]]) -> List[List[float]]:
        out: List[List[float]] = []
        for row in vectors:
            scaled = []
            for i, value in enumerate(row):
                denom = self.std[i] if self.std[i] > 1e-12 else 1.0
                scaled.append((value - self.mean[i]) / denom)
            out.append(scaled)
        return out


class LogisticBinaryClassifier:
    def __init__(self, learning_rate: float = 0.05, epochs: int = 250, l2: float = 0.0005):
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.l2 = l2
        self.weights: List[float] = []
        self.bias = 0.0

    @staticmethod
    def _sigmoid(z: float) -> float:
        if z >= 0:
            ez = math.exp(-z)
            return 1 / (1 + ez)
        ez = math.exp(z)
        return ez / (1 + ez)

    def fit(self, x: Sequence[Sequence[float]], y: Sequence[int]) -> None:
        if not x:
            raise ValueError("Cannot fit model on empty dataset")
        n = len(x)
        d = len(x[0])
        self.weights = [0.0] * d
        self.bias = 0.0
        for _ in range(self.epochs):
            grad_w = [0.0] * d
            grad_b = 0.0
            for row, label in zip(x, y):
                z = self.bias
                for j in range(d):
                    z += self.weights[j] * row[j]
                p = self._sigmoid(z)
                error = p - label
                grad_b += error
                for j in range(d):
                    grad_w[j] += error * row[j]
            grad_b /= n
            for j in range(d):
                grad_w[j] = (grad_w[j] / n) + (self.l2 * self.weights[j])
                self.weights[j] -= self.learning_rate * grad_w[j]
            self.bias -= self.learning_rate * grad_b

    def predict_proba(self, x: Sequence[Sequence[float]]) -> List[float]:
        probs: List[float] = []
        for row in x:
            z = self.bias
            for j, value in enumerate(row):
                z += self.weights[j] * value
            probs.append(self._sigmoid(z))
        return probs
