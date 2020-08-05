# -*- encoding: utf-8 -*-
# @Time    :   2020/08/04
# @Author  :   Kaiyuan Li
# @email   :   tsotfsk@outlook.com

# UPDATE
# @Time    :   2020/08/04
# @Author  :   Kaiyuan Li
# @email   :   tsotfsk@outlook.com


from enum import Enum
import numpy as np


# class TOPK_ARGS(Enum):
#     POS_INDEX = 0
#     POS_LEN = 1

#     NDCG = (POS_INDEX, POS_LEN)
#     MAP = (POS_INDEX, POS_LEN)
#     RECALL = (POS_INDEX, POS_LEN)
#     MRR = (POS_INDEX)
#     HIT = (POS_INDEX)
#     PRECISION = (POS_INDEX)


class TOPK_METRICS(Enum):
    NDCG = 'ndcg'
    MRR = 'mrr'
    MAP = 'map'
    HIT = 'hit'
    RECALL = 'recall'
    PRECISION = 'precision'


class LOSS_METRICS(Enum):
    MAE = 'mae'
    RMSE = 'rmse'
    LOGLOSS = 'logloss'
    AUC = 'auc'


class ITEM_METRIC(Enum):
    pass


def trunc(scores, method):
    """Round the scores by using the given method

    Args:
        scores (np.ndarray): scores
        method (str): one of ['ceil', 'floor', 'around']

    Raises:
        NotImplementedError: method error

    Returns:
        (np.ndarray): processed scores
    """

    try:
        cut_method = getattr(np, method)
    except NotImplementedError as e:
        raise NotImplementedError("module 'numpy' has no fuction named '{}'".format(method))
    scores = cut_method(scores)
    return scores


def cutoff(scores, threshold):
    """cut of the scores based on threshold

    Args:
        scores (np.ndarray): scores
        threshold (float): between 0 and 1

    Returns:
        (np.ndarray): processed scores
    """    
    return np.where(scores > threshold, 1, 0)