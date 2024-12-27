import numpy as np
from typing import Dict, Union

def fast_ranks(x):
    """Simple ranking function using numpy only"""
    temp = x.argsort()
    ranks = np.empty_like(temp)
    ranks[temp] = np.arange(len(x))
    return (ranks + 1) / (len(x) + 1)  # Add 1 to avoid 0s

def calculate_rank_score(df, rule, target_column='species'):
    """
    Enhanced scoring function that balances separation quality with class recall
    while considering within-class spread.
    """
    def matches_rule(row, rule):
        for feature, value in rule.items():
            if feature == target_column:
                continue
            if isinstance(value, tuple):
                min_val, max_val = value
                if not (min_val <= row[feature] <= max_val):
                    return False
            else:
                if row[feature] != value:
                    return False
        return True

    # Get matching samples
    matching_mask = df.apply(lambda row: matches_rule(row, rule), axis=1)

    if matching_mask.sum() == 0:
        return {
            'score': 0.0,
            'separation_score': 0.0,
            'recall_score': 0.0,
            'coverage': 0.0,
            'matching_samples': 0,
            'dominant_class': None
        }

    matching_df = df[matching_mask]
    non_matching_df = df[~matching_mask]

    # Get class distribution and dominant class
    class_counts = matching_df[target_column].value_counts()
    dominant_class = class_counts.index[0]

    # Calculate class recall for dominant class
    total_in_class = len(df[df[target_column] == dominant_class])
    matching_in_class = len(matching_df[matching_df[target_column] == dominant_class])
    class_recall = matching_in_class / total_in_class if total_in_class > 0 else 0

    # Calculate feature scores for continuous features
    continuous_features = [f for f, v in rule.items()
                         if isinstance(v, tuple) and f != target_column]
    feature_scores = {}

    for feature in continuous_features:
        values = df[feature].values
        normalized_ranks = fast_ranks(values)

        matching_ranks = normalized_ranks[matching_mask]
        nonmatching_ranks = normalized_ranks[~matching_mask]

        # Median separation between classes
        rank_separation = abs(np.percentile(matching_ranks, 50) -
                            np.percentile(nonmatching_ranks, 50))

        # Within-class spread for target class
        target_mask = matching_df[target_column] == dominant_class
        if target_mask.any():
            target_ranks = matching_ranks[target_mask]
            rank_spread = np.percentile(target_ranks, 75) - np.percentile(target_ranks, 25)
            # Penalize high spread within target class
            spread_penalty = 1 / (1 + rank_spread)
        else:
            spread_penalty = 0

        feature_scores[feature] = rank_separation * spread_penalty

    # Calculate separation score
    separation_score = np.mean(list(feature_scores.values())) if feature_scores else 0

    # Calculate purity (proportion of dominant class in matches)
    purity = class_counts.iloc[0] / len(matching_df)

    # Calculate coverage (relative to total dataset)
    coverage = len(matching_df) / len(df)

    # For categorical features, boost score if they help with classification
    categorical_features = [f for f, v in rule.items()
                          if not isinstance(v, tuple) and f != target_column]
    if categorical_features:
        categorical_boost = sum(1 for f in categorical_features
                              if rule[f] == dominant_class) / len(categorical_features)
    else:
        categorical_boost = 0

    # Combine scores with emphasis on meaningful coverage
    # Calculate minimum required coverage based on dataset size
    min_coverage = max(0.1, 10 / len(df))  # At least 10 samples or 10% of data

    # Apply coverage penalty if below minimum
    coverage_score = coverage if coverage >= min_coverage else coverage * (coverage / min_coverage)

    # Combine scores favoring rules with good separation AND good coverage
    base_score = (
        separation_score * 0.4 +  # Continuous feature separation
        class_recall * 0.3 +      # Recall of dominant class
        purity * 0.3             # Class purity in matches
    )

    # Use sigmoid-like function to favor higher coverage when base_score is good
    coverage_weight = 1 / (1 + np.exp(-10 * (base_score - 0.5)))  # Sigmoid centered at 0.5
    final_score = base_score * (1 + coverage_weight * coverage)

    return {
        'score': final_score,
        'separation_score': separation_score,
        'recall_score': class_recall,
        'purity': purity,
        'coverage': coverage,
        'matching_samples': len(matching_df),
        'dominant_class': dominant_class,
        'feature_scores': feature_scores
    }

def score_improvement(new_score, base_score, new_coverage, base_coverage,
                     coverage_weight=0.1):
    """Calculate improvement in score with coverage penalty/bonus"""
    return (new_score - base_score) + coverage_weight * (new_coverage - base_coverage)