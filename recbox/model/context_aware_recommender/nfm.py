# -*- coding: utf-8 -*-
# @Time   : 2020/7/14
# @Author : Zihan Lin
# @Email  : linzihan.super@foxmail.com
# @File   : nfm.py
"""
Reference:
He X, Chua T S. "Neural factorization machines for sparse predictive analytics" in SIGIR 2017
"""

import torch
import torch.nn as nn
from torch.nn.init import xavier_normal_, constant_

from ..layers import BaseFactorizationMachine, MLPLayers
from .context_recommender import ContextRecommender


class NFM(ContextRecommender):
    def __init__(self, config, dataset):
        super(NFM, self).__init__(config, dataset)

        self.LABEL = config['LABEL_FIELD']
        self.mlp_hidden_size = config['mlp_hidden_size']
        self.dropout = config['dropout']

        size_list = [self.embedding_size] + self.mlp_hidden_size
        self.fm = BaseFactorizationMachine(reduce_sum=False)
        self.bn = nn.BatchNorm1d(num_features=self.embedding_size)
        self.mlp_layers = MLPLayers(size_list,
                                    self.dropout,
                                    activation='sigmoid',
                                    bn=True)
        self.predict_layer = nn.Linear(self.mlp_hidden_size[-1], 1, bias=False)
        self.sigmoid = nn.Sigmoid()
        self.loss = nn.BCELoss()

        self.apply(self.init_weights)

    def init_weights(self, module):
        if isinstance(module, nn.Embedding):
            xavier_normal_(module.weight.data)
        elif isinstance(module, nn.Linear):
            xavier_normal_(module.weight.data)
            if module.bias is not None:
                constant_(module.bias.data, 0)

    def forward(self, interaction):
        # sparse_embedding shape: [batch_size, num_token_seq_field+num_token_field, embed_dim] or None
        # dense_embedding shape: [batch_size, num_float_field] or [batch_size, num_float_field, embed_dim] or None
        sparse_embedding, dense_embedding = self.embed_input_fields(
            interaction)
        all_embeddings = []
        if sparse_embedding is not None:
            all_embeddings.append(sparse_embedding)
        if dense_embedding is not None and len(dense_embedding.shape) == 3:
            all_embeddings.append(dense_embedding)
        nfm_all_embeddings = torch.cat(
            all_embeddings, dim=1)  # [batch_size, num_field, embed_dim]
        bn_nfm_all_embeddings = self.bn(self.fm(nfm_all_embeddings))

        output = self.sigmoid(
            self.predict_layer(self.mlp_layers(bn_nfm_all_embeddings)) +
            self.first_order_linear(interaction))
        return output.squeeze()

    def calculate_loss(self, interaction):
        label = interaction[self.LABEL]
        output = self.forward(interaction)
        return self.loss(output, label)

    def predict(self, interaction):
        return self.forward(interaction)
