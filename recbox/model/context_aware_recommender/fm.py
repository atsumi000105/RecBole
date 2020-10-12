# -*- coding: utf-8 -*-
# @Time   : 2020/7/8 10:09
# @Author : Shanlei Mu
# @Email  : slmu@ruc.edu.cn
# @File   : fm.py

# UPDATE:
# @Time   : 2020/8/13,
# @Author : Zihan Lin
# @Email  : linzihan.super@foxmain.com
r"""
recbox.model.context_aware_recommender.fm
################################################
Reference:
Steffen Rendle et al. "Factorization Machines." in ICDM 2010.
"""

import torch
import torch.nn as nn
from torch.nn.init import xavier_normal_

from recbox.model.layers import BaseFactorizationMachine
from recbox.model.context_aware_recommender.context_recommender import ContextRecommender


class FM(ContextRecommender):
    """Factorization Machine considers the second-order interaction with features to predict the final score.

    """

    def __init__(self, config, dataset):

        super(FM, self).__init__(config, dataset)

        self.LABEL = config['LABEL_FIELD']
        self.fm = BaseFactorizationMachine(reduce_sum=True)
        self.sigmoid = nn.Sigmoid()
        self.loss = nn.BCELoss()

        self.apply(self.init_weights)

    def init_weights(self, module):
        if isinstance(module, nn.Embedding):
            xavier_normal_(module.weight.data)

    def forward(self, interaction):
        # sparse_embedding shape: [batch_size, num_token_seq_field+num_token_field, embed_dim] or None
        # dense_embedding shape: [batch_size, num_float_field] or [batch_size, num_float_field, embed_dim] or None
        sparse_embedding, dense_embedding = self.embed_input_fields(interaction)
        all_embeddings = []
        if sparse_embedding is not None:
            all_embeddings.append(sparse_embedding)
        if dense_embedding is not None and len(dense_embedding.shape) == 3:
            all_embeddings.append(dense_embedding)
        fm_all_embeddings = torch.cat(all_embeddings, dim=1)
        y = self.sigmoid(self.first_order_linear(interaction) + self.fm(fm_all_embeddings))
        return y.squeeze()

    def calculate_loss(self, interaction):
        label = interaction[self.LABEL]

        output = self.forward(interaction)
        return self.loss(output, label)

    def predict(self, interaction):
        return self.forward(interaction)
