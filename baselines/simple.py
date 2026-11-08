"""Simple prediction baselines (spec 14): majority, student-accuracy, concept-difficulty."""
from __future__ import annotations

import numpy as np
import pandas as pd


def majority(df: pd.DataFrame, train_acc: float) -> np.ndarray:
    return np.full(len(df), train_acc)


def student_accuracy(df: pd.DataFrame) -> np.ndarray:
    """Causal EWMA of the student's past correctness (the 'ability' feature)."""
    return df["ability"].to_numpy()


def concept_difficulty(df: pd.DataFrame) -> np.ndarray:
    return 1.0 - df["concept_difficulty"].to_numpy()
