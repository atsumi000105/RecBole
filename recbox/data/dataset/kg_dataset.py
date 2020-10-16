# @Time   : 2020/9/3
# @Author : Yupeng Hou
# @Email  : houyupeng@ruc.edu.cn

# UPDATE:
# @Time   : 2020/10/16, 2020/9/15, 2020/9/22
# @Author : Yupeng Hou, Xingyu Pan, Yushuo Chen
# @Email  : houyupeng@ruc.edu.cn, panxy@ruc.edu.cn, chenyushuo@ruc.edu.cn

"""
recbox.data.kg_dataset
##########################
"""

import os
from collections import Counter

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
import torch

from recbox.data.dataset import Dataset
from recbox.data.utils import dlapi
from recbox.utils import FeatureSource, FeatureType


class KnowledgeBasedDataset(Dataset):
    def __init__(self, config, saved_dataset=None):
        super().__init__(config, saved_dataset=saved_dataset)

    def _get_preset(self):
        super()._get_preset()
        self.field2ent_level = {}

    def _get_field_from_config(self):
        super()._get_field_from_config()

        self.head_entity_field = self.config['HEAD_ENTITY_ID_FIELD']
        self.tail_entity_field = self.config['TAIL_ENTITY_ID_FIELD']
        self.relation_field = self.config['RELATION_ID_FIELD']
        self.entity_field = self.config['ENTITY_ID_FIELD']
        self._check_field('head_entity_field', 'tail_entity_field', 'relation_field', 'entity_field')
        self.set_field_property(self.entity_field, FeatureType.TOKEN, FeatureSource.KG, 1)

        self.logger.debug('relation_field: {}'.format(self.relation_field))
        self.logger.debug('entity_field: {}'.format(self.entity_field))

    def _data_processing(self):
        self._set_field2ent_level()
        self.feat_list = self._build_feat_list()
        if self.benchmark_filename_list is None:
            self._filter_nan_user_or_item()
            self._filter_by_inter_num()
            self._filter_by_field_value()
            self._filter_link()
            self._reset_index()

        self._remap_ID_all()
        self._user_item_feat_preparation()
        self._fill_nan()
        self._set_label_by_threshold()
        self._normalize()
        self._preload_weight_matrix()

    def _filter_link(self):
        item_tokens = self._get_rec_item_token()
        ent_tokens = self._get_entity_token()
        illegal_item = set()
        illegal_ent = set()
        for item in self.item2entity:
            ent = self.item2entity[item]
            if item not in item_tokens or ent not in ent_tokens:
                illegal_item.add(item)
                illegal_ent.add(ent)
        for item in illegal_item:
            del self.item2entity[item]
        for ent in illegal_ent:
            del self.entity2item[ent]

    def _load_data(self, token, dataset_path):
        super()._load_data(token, dataset_path)
        self.kg_feat = self._load_kg(self.dataset_name, self.dataset_path)
        self.item2entity, self.entity2item = self._load_link(self.dataset_name, self.dataset_path)

    def __str__(self):
        info = [super().__str__(),
                'The number of entities: {}'.format(self.entity_num),
                'The number of relations: {}'.format(self.relation_num),
                'The number of triples: {}'.format(len(self.kg_feat)),
                'The number of items that have been linked to KG: {}'.format(len(self.item2entity))]
        return '\n'.join(info)

    def _build_feat_list(self):
        feat_list = super()._build_feat_list()
        if self.kg_feat is not None:
            feat_list.append(self.kg_feat)
        return feat_list

    def _restore_saved_dataset(self, saved_dataset):
        raise NotImplementedError()

    def save(self, filepath):
        raise NotImplementedError()

    def _load_kg(self, token, dataset_path):
        self.logger.debug('loading kg from [{}]'.format(dataset_path))
        kg_path = os.path.join(dataset_path, '{}.{}'.format(token, 'kg'))
        if not os.path.isfile(kg_path):
            raise ValueError('[{}.{}] not found in [{}]'.format(token, 'kg', dataset_path))
        df = pd.read_csv(kg_path, delimiter=self.config['field_separator'])
        field_names = []
        for field_type in df.columns:
            field, ftype = field_type.split(':')
            field_names.append(field)
            assert ftype == 'token', 'kg data requires fields with type token'
            self.set_field_property(field, FeatureType.TOKEN, FeatureSource.KG, 1)
        df.columns = field_names
        self._check_kg(df)
        return df

    def _check_kg(self, kg):
        kg_warn_message = 'kg data requires field [{}]'
        assert self.head_entity_field in kg, kg_warn_message.format(self.head_entity_field)
        assert self.tail_entity_field in kg, kg_warn_message.format(self.tail_entity_field)
        assert self.relation_field in kg, kg_warn_message.format(self.relation_field)

    def _load_link(self, token, dataset_path):
        self.logger.debug('loading link from [{}]'.format(dataset_path))
        link_path = os.path.join(dataset_path, '{}.{}'.format(token, 'link'))
        if not os.path.isfile(link_path):
            raise ValueError('[{}.{}] not found in [{}]'.format(token, 'link', dataset_path))
        df = pd.read_csv(link_path, delimiter=self.config['field_separator'])
        field_names = []
        for field_type in df.columns:
            field, ftype = field_type.split(':')
            field_names.append(field)
            assert ftype == 'token', 'kg data requires fields with type token'
        df.columns = field_names
        self._check_link(df)

        item2entity, entity2item = {}, {}
        for item_id, entity_id in zip(df[self.iid_field].values, df[self.entity_field].values):
            item2entity[item_id] = entity_id
            entity2item[entity_id] = item_id
        return item2entity, entity2item

    def _check_link(self, link):
        link_warn_message = 'link data requires field [{}]'
        assert self.entity_field in link, link_warn_message.format(self.entity_field)
        assert self.iid_field in link, link_warn_message.format(self.iid_field)

    def _get_fields_in_same_space(self):
        fields_in_same_space = super()._get_fields_in_same_space()
        fields_in_same_space = [
            _ for _ in fields_in_same_space if not self._contain_ent_field(_)
        ]
        ent_fields = self._get_ent_fields_in_same_space()
        for field_set in fields_in_same_space:
            if self.iid_field in field_set:
                field_set.update(ent_fields)
        return fields_in_same_space

    def _contain_ent_field(self, field_set):
        flag = False
        flag |= self.head_entity_field in field_set
        flag |= self.tail_entity_field in field_set
        flag |= self.entity_field in field_set
        return flag

    def _get_ent_fields_in_same_space(self):
        fields_in_same_space = super()._get_fields_in_same_space()

        ent_fields = {self.head_entity_field, self.tail_entity_field}
        for field_set in fields_in_same_space:
            if self._contain_ent_field(field_set):
                field_set = self._remove_ent_field(field_set)
                ent_fields.update(field_set)
        self.logger.debug('ent_fields: {}'.format(fields_in_same_space))
        return ent_fields

    def _remove_ent_field(self, field_set):
        for field in [self.head_entity_field, self.tail_entity_field, self.entity_field]:
            if field in field_set:
                field_set.remove(field)
        return field_set

    def _set_field2ent_level(self):
        fields_in_same_space = self._get_fields_in_same_space()
        for field_set in fields_in_same_space:
            if self.iid_field in field_set:
                for field in field_set:
                    self.field2ent_level[field] = 'rec'
        ent_fields = self._get_ent_fields_in_same_space()
        for field in ent_fields:
            self.field2ent_level[field] = 'ent'

    def _fields_by_ent_level(self, ent_level):
        ret = []
        for field in self.field2ent_level:
            if self.field2ent_level[field] == ent_level:
                ret.append(field)
        return ret

    @property
    @dlapi.set()
    def rec_level_ent_fields(self):
        return self._fields_by_ent_level('rec')

    @property
    @dlapi.set()
    def ent_level_ent_fields(self):
        return self._fields_by_ent_level('ent')

    def _remap_entities_by_link(self):
        for ent_field in self.ent_level_ent_fields:
            source = self.field2source[ent_field]
            if not isinstance(source, str):
                source = source.value
            feat = getattr(self, '{}_feat'.format(source))
            entity_list = feat[ent_field].values
            for i, entity_id in enumerate(entity_list):
                if entity_id in self.entity2item:
                    entity_list[i] = self.entity2item[entity_id]
            feat[ent_field] = entity_list

    def _get_rec_item_token(self):
        field_set = set(self.rec_level_ent_fields)
        remap_list = self._get_remap_list(field_set)
        tokens, _ = self._concat_remaped_tokens(remap_list)
        return set(tokens)

    def _get_entity_token(self):
        field_set = set(self.ent_level_ent_fields)
        remap_list = self._get_remap_list(field_set)
        tokens, _ = self._concat_remaped_tokens(remap_list)
        return set(tokens)

    def _reset_ent_remapID(self, field, new_id_token):
        token2id = {}
        for i, token in enumerate(new_id_token):
            token2id[token] = i
        idmap = {}
        for i, token in enumerate(self.field2id_token[field]):
            if token not in token2id:
                continue
            new_idx = token2id[token]
            idmap[i] = new_idx
        source = self.field2source[field]
        if not isinstance(source, str):
            source = source.value
        if source == 'item_id':
            feats = [self.inter_feat]
            if self.item_feat is not None:
                feats.append(self.item_feat)
        else:
            feats = [getattr(self, '{}_feat'.format(source))]
        for feat in feats:
            old_idx = feat[field].values
            new_idx = np.array([idmap[_] for _ in old_idx])
            feat[field] = new_idx

    def _sort_remaped_entities(self, item_tokens):
        item2order = {}
        for token in self.field2id_token[self.iid_field]:
            if token == '[PAD]':
                item2order[token] = 0
            elif token in item_tokens and token not in self.item2entity:
                item2order[token] = 1
            elif token in self.item2entity or token in self.entity2item:
                item2order[token] = 2
            else:
                item2order[token] = 3
        item_ent_token_list = list(self.field2id_token[self.iid_field])
        item_ent_token_list.sort(key=lambda t: item2order[t])
        order_list = [item2order[_] for _ in item_ent_token_list]
        order_cnt = Counter(order_list)
        layered_num = []
        for i in range(4):
            layered_num.append(order_cnt[i])
        layered_num = np.cumsum(np.array(layered_num))
        new_id_token = item_ent_token_list[:layered_num[-2]]
        for field in self.rec_level_ent_fields:
            self._reset_ent_remapID(field, new_id_token)
            self.field2id_token[field] = new_id_token
        new_id_token = item_ent_token_list[:layered_num[-1]]
        new_id_token = [self.item2entity[_] if _ in self.item2entity else _ for _ in new_id_token]
        for field in self.ent_level_ent_fields:
            self._reset_ent_remapID(field, item_ent_token_list[:layered_num[-1]])
            self.field2id_token[field] = new_id_token
        self.field2id_token[self.entity_field] = item_ent_token_list[:layered_num[-1]]

    def _remap_ID_all(self):
        # import ipdb; ipdb.set_trace()
        self._remap_entities_by_link()
        item_tokens = self._get_rec_item_token()
        super()._remap_ID_all()
        self._sort_remaped_entities(item_tokens)
        self.field2id_token[self.relation_field].append('[UI-Relation]')

    @property
    @dlapi.set()
    def relation_num(self):
        return self.num(self.relation_field)

    @property
    @dlapi.set()
    def entity_num(self):
        return self.num(self.entity_field)

    @property
    @dlapi.set()
    def head_entities(self):
        return self.kg_feat[self.head_entity_field].values

    @property
    @dlapi.set()
    def tail_entities(self):
        return self.kg_feat[self.tail_entity_field].values

    @property
    @dlapi.set()
    def relations(self):
        return self.kg_feat[self.relation_field].values

    @property
    @dlapi.set()
    def entities(self):
        return np.arange(self.entity_num)

    @dlapi.set()
    def kg_graph(self, form='coo', value_field=None):
        args = [self.kg_feat, self.head_entity_field, self.tail_entity_field, form, value_field]
        if form in ['coo', 'csr']:
            return self._create_sparse_matrix(*args)
        elif form in ['dgl', 'pyg']:
            return self._create_graph(*args)
        else:
            raise NotImplementedError('kg graph format [{}] has not been implemented.')

    def _create_ckg_sparse_matrix(self, form='coo', show_relation=False):
        user_num = self.user_num

        hids = self.kg_feat[self.head_entity_field].values + user_num
        tids = self.kg_feat[self.tail_entity_field].values + user_num

        uids = self.inter_feat[self.uid_field].values
        iids = self.inter_feat[self.iid_field].values + user_num

        ui_rel_num = len(uids)
        ui_rel_id = self.relation_num - 1
        assert self.field2id_token[self.relation_field][ui_rel_id] == '[UI-Relation]'

        src = np.concatenate([uids, iids, hids])
        tgt = np.concatenate([iids, uids, tids])

        if not show_relation:
            data = np.ones(len(src))
        else:
            kg_rel = self.kg_feat[self.relation_field].values
            ui_rel = np.full(2 * ui_rel_num, ui_rel_id, dtype=kg_rel.dtype)
            data = np.concatenate([ui_rel, kg_rel])
        node_num = self.entity_num + self.user_num
        mat = coo_matrix((data, (src, tgt)), shape=(node_num, node_num))
        if form == 'coo':
            return mat
        elif form == 'csr':
            return mat.tocsr()
        else:
            raise NotImplementedError('sparse matrix format [{}] has not been implemented.'.format(form))

    def _create_ckg_graph(self, form='dgl', show_relation=False):
        user_num = self.user_num

        kg_tensor = self._dataframe_to_interaction(self.kg_feat)
        inter_tensor = self._dataframe_to_interaction(self.inter_feat)

        head_entity = kg_tensor[self.head_entity_field] + user_num
        tail_entity = kg_tensor[self.tail_entity_field] + user_num

        user = inter_tensor[self.uid_field]
        item = inter_tensor[self.iid_field] + user_num

        src = torch.cat([user, item, head_entity])
        tgt = torch.cat([item, user, tail_entity])

        if show_relation:
            ui_rel_num = user.shape[0]
            ui_rel_id = self.relation_num - 1
            assert self.field2id_token[self.relation_field][ui_rel_id] == '[UI-Relation]'
            kg_rel = kg_tensor[self.relation_field]
            ui_rel = torch.full((2 * ui_rel_num,), ui_rel_id, dtype=kg_rel.dtype)
            edge = torch.cat([ui_rel, kg_rel])

        if form == 'dgl':
            import dgl
            graph = dgl.graph((src, tgt))
            if show_relation:
                graph.edata[self.relation_field] = edge
            return graph
        elif form == 'pyg':
            from torch_geometric.data import Data
            edge_attr = edge if show_relation else None
            graph = Data(edge_index=torch.stack([src, tgt]), edge_attr=edge_attr)
            return graph
        else:
            raise NotImplementedError('graph format [{}] has not been implemented.'.format(form))

    @dlapi.set()
    def ckg_graph(self, form='coo', value_field=None):
        if value_field is not None and value_field != self.relation_field:
            raise ValueError('value_field [{}] can only be [{}] in ckg_graph.'.format(
                value_field, self.relation_field
            ))
        show_relation = value_field is not None

        if form in ['coo', 'csr']:
            return self._create_ckg_sparse_matrix(form, show_relation)
        elif form in ['dgl', 'pyg']:
            return self._create_ckg_graph(form, show_relation)
        else:
            raise NotImplementedError('ckg graph format [{}] has not been implemented.')
