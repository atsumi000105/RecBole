# -*- coding: utf-8 -*-
# @Author : Yupeng Hou
# @Email  : houyupeng@ruc.edu.cn
# @File   : dataloader.py

import operator
from functools import reduce
import pandas as pd
import numpy as np
import torch
import torch.nn.utils.rnn as rnn_utils
from sampler import Sampler
from .interaction import Interaction


class AbstractDataLoader(object):
    def __init__(self, config, dataset,
                 batch_size=1, shuffle=False):
        self.config = config
        self.dataset = dataset
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.pr = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.pr >= self.pr_end:
            self.pr = 0
            if self.shuffle:
                self._shuffle()
            raise StopIteration()
        cur_data = self._next_dataframe()
        return self._dataframe_to_interaction(cur_data)

    @property
    def pr_end(self):
        raise NotImplementedError('Method [pr_end] should be implemented')

    def _shuffle(self):
        raise NotImplementedError('Method [shuffle] should be implemented.')

    def _next_dataframe(self):
        raise NotImplementedError('Method [next_dataframe] should be implemented.')

    def _dataframe_to_interaction(self, data):
        data = data.to_dict(orient='list')
        seqlen = self.dataset.field2seqlen
        for k in data:
            ftype = self.dataset.field2type[k]
            if ftype == 'token':
                data[k] = torch.LongTensor(data[k])
            elif ftype == 'float':
                data[k] = torch.FloatTensor(data[k])
            elif ftype == 'token_seq':
                data = [torch.LongTensor(d[:seqlen[k]]) for d in data[k]]  # TODO  cutting strategy?
                data[k] = rnn_utils.pad_sequence(data, batch_first=True)
            elif ftype == 'float_seq':
                data = [torch.FloatTensor(d[:seqlen[k]]) for d in data[k]]  # TODO  cutting strategy?
                data[k] = rnn_utils.pad_sequence(data, batch_first=True)
            else:
                raise ValueError('Illegal ftype [{}]'.format(ftype))
        return Interaction(data)

    def set_batch_size(self, batch_size):
        if self.pr != 0:
            raise PermissionError('Cannot change dataloader\'s batch_size while iteration')
        if self.batch_size != batch_size:
            self.batch_size = batch_size
            # TODO  batch size is changed


class NegSampleBasedDataLoader(AbstractDataLoader):
    def __init__(self, config, dataset, sampler, phase, neg_sample_args,
                 batch_size=1, dl_format='pointwise', shuffle=False):
        if dl_format not in ['pointwise', 'pairwise']:
            raise ValueError('dl_format [{}] has not been implemented'.format(dl_format))
        if neg_sample_args['strategy'] not in ['by', 'to']:
            raise ValueError('neg_sample strategy [{}] has not been implemented'.format(neg_sample_args['strategy']))

        super(NegSampleBasedDataLoader, self).__init__(config, dataset, batch_size, shuffle)

        self.sampler = sampler
        self.phase = phase
        self.neg_sample_args = neg_sample_args
        self.dl_format = dl_format
        self.real_time_neg_sampling = self.neg_sample_args['real_time']

        self._batch_size_adaptation()
        if not self.real_time_neg_sampling:
            self._pre_neg_sampling()

    def _batch_size_adaptation(self):
        raise NotImplementedError('Method [batch_size_adaptation] should be implemented.')

    def _pre_neg_sampling(self):
        raise NotImplementedError('Method [pre_neg_sampling] should be implemented.')

    def _neg_sampling(self, inter_feat):
        raise NotImplementedError('Method [neg_sampling] should be implemented.')


class GeneralInteractionBasedDataLoader(NegSampleBasedDataLoader):
    def __init__(self, config, dataset, sampler, phase, neg_sample_args,
                 batch_size=1, dl_format='pointwise', shuffle=False):
        if neg_sample_args['strategy'] != 'by':
            raise ValueError('neg_sample strategy in GeneralInteractionBasedDataLoader() should be `by`')
        if dl_format == 'pairwise' and neg_sample_args['by'] != 1:
            raise ValueError('Pairwise dataloader can only neg sample by 1')

        self.neg_sample_by = neg_sample_args['by']

        if dl_format == 'pointwise':
            self.label_field = config['LABEL_FIELD']
            dataset.field2type[self.label_field] = 'float'
            dataset.field2source[self.label_field] = 'inter'
            dataset.field2seqlen[self.label_field] = 1

        super(GeneralInteractionBasedDataLoader, self).__init__(config, dataset, sampler, phase, neg_sample_args,
                                                                batch_size, dl_format, shuffle)

        if self.dl_format == 'pairwise':
            neg_prefix = self.config['NEG_PREFIX']
            iid_field = self.config['ITEM_ID_FIELD']

            columns = [iid_field] if self.dataset.item_feat is None else self.dataset.item_feat.columns
            for item_feat_col in columns:
                neg_item_feat_col = neg_prefix + item_feat_col
                self.dataset.field2type[neg_item_feat_col] = self.dataset.field2type[item_feat_col]
                self.dataset.field2source[neg_item_feat_col] = self.dataset.field2source[item_feat_col]
                self.dataset.field2seqlen[neg_item_feat_col] = self.dataset.field2seqlen[item_feat_col]

    def _batch_size_adaptation(self):
        if self.dl_format == 'pairwise':
            self.step = self.batch_size
            return
        self.times = 1 + self.neg_sample_by
        batch_num = self.batch_size // self.times
        new_batch_size = (batch_num + 1) * self.times
        self.step = batch_num + 1 if self.real_time_neg_sampling else new_batch_size
        self.set_batch_size(new_batch_size)

    @property
    def pr_end(self):
        return len(self.dataset)

    def _shuffle(self):
        self.dataset.shuffle()

    def _next_dataframe(self):
        cur_data = self.dataset[self.pr: self.pr + self.step]
        self.pr += self.step
        if self.real_time_neg_sampling:
            cur_data = self._neg_sampling(cur_data)
        return cur_data

    def _pre_neg_sampling(self):
        self.dataset.inter_feat = self._neg_sampling(self.dataset.inter_feat)

    def _neg_sampling(self, inter_feat):
        uid_field = self.config['USER_ID_FIELD']
        iid_field = self.config['ITEM_ID_FIELD']
        uids = inter_feat[uid_field].to_list()
        neg_iids = self.sampler.sample_by_user_ids(self.phase, uids, self.neg_sample_by)
        if self.dl_format == 'pointwise':
            sampling_func = self._neg_sample_by_point_wise_sampling
        elif self.dl_format == 'pairwise':
            sampling_func = self._neg_sample_by_pair_wise_sampling
        else:
            raise ValueError('`neg sampling by` with dl_format [{}] not been implemented'.format(self.dl_format))
        return sampling_func(uid_field, iid_field, neg_iids, inter_feat)

    def _neg_sample_by_pair_wise_sampling(self, uid_field, iid_field, neg_iids, inter_feat):
        neg_prefix = self.config['NEG_PREFIX']
        neg_item_id = neg_prefix + iid_field
        inter_feat.insert(len(inter_feat.columns), neg_item_id, neg_iids)

        if self.dataset.item_feat is not None:
            neg_item_feat = self.dataset.item_feat.add_prefix(neg_prefix)
            inter_feat = pd.merge(inter_feat, neg_item_feat,
                                  on=neg_item_id, how='left', suffixes=('_inter', '_item'))

        return inter_feat

    def _neg_sample_by_point_wise_sampling(self, uid_field, iid_field, neg_iids, inter_feat):
        pos_inter_num = len(inter_feat)

        new_df = pd.concat([inter_feat] * self.times, ignore_index=True)
        new_df[iid_field].values[pos_inter_num:] = neg_iids

        labels = np.zeros(pos_inter_num * self.times, dtype=np.int64)
        labels[: pos_inter_num] = 1
        new_df[self.label_field] = labels

        return self.dataset.join(new_df) if self.real_time_neg_sampling else new_df


class GeneralGroupedDataLoader(NegSampleBasedDataLoader):
    def __init__(self, config, dataset, sampler, phase, neg_sample_args,
                 batch_size=1, dl_format='pointwise', shuffle=False):
        if neg_sample_args['strategy'] != 'to':
            raise ValueError('neg_sample strategy in GeneralGroupedDataLoader() should be `to`')
        if dl_format == 'pairwise':
            raise ValueError('pairwise dataloader cannot neg sample to')

        self.uid2items = dataset.uid2items
        self.full = (neg_sample_args['to'] == -1)

        super(GeneralGroupedDataLoader, self).__init__(config, dataset, sampler, phase, neg_sample_args,
                                                       batch_size, dl_format, shuffle)

        label_field = self.config['LABEL_FIELD']
        self.dataset.field2type[label_field] = 'float'
        self.dataset.field2source[label_field] = 'inter'
        self.dataset.field2seqlen[label_field] = 1

    def _batch_size_adaptation(self):
        if self.neg_sample_args['to'] == -1:
            self.neg_sample_args['to'] = self.dataset.item_num
        batch_num = self.batch_size // self.neg_sample_args['to']
        new_batch_size = (batch_num + 1) * self.neg_sample_args['to']
        self.step = batch_num + 1
        self.set_batch_size(new_batch_size)

    @property
    def pr_end(self):
        if self.real_time_neg_sampling:
            return len(self.uid2items)
        else:
            return len(self.dataset)

    def _shuffle(self):
        if self.real_time_neg_sampling:
            self.uid2items = self.uid2items.sample(frac=1).reset_index(drop=True)
        else:
            self.dataset.shuffle()

    @property
    def next_pr(self):
        return self.next[self.pr]

    def _next_dataframe(self):
        if self.real_time_neg_sampling:
            cur_data = self._neg_sampling(self.uid2items[self.pr: self.pr + self.step])
            self.pr += self.step
        else:
            cur_data = self.dataset[self.pr: self.next_pr]
            self.pr = self.next_pr
        return cur_data

    def _pre_neg_sampling(self):
        self.dataset.inter_feat = self._neg_sampling(self.uid2items)

    def _neg_sampling(self, uid2items):
        uid_field = self.config['USER_ID_FIELD']
        iid_field = self.config['ITEM_ID_FIELD']
        label_field = self.config['LABEL_FIELD']
        neg_sample_to = self.neg_sample_args['to']
        new_inter = {
            uid_field: np.zeros(len(uid2items) * neg_sample_to, dtype=np.int64),
            iid_field: np.zeros(len(uid2items) * neg_sample_to, dtype=np.int64),
            label_field: np.zeros(len(uid2items) * neg_sample_to, dtype=np.int64),
        }

        new_inter_num = 0
        for i, row in enumerate(uid2items.itertuples()):
            uid = getattr(row, uid_field)
            if self.full:
                pos_item_id = getattr(row, iid_field)
                pos_num = len(pos_item_id)
                neg_item_id = self.sampler.sample_full_by_user_id(self.phase, uid)
                neg_num = len(neg_item_id)
            else:
                pos_item_id = getattr(row, iid_field)[:neg_sample_to - 1]
                pos_num = len(pos_item_id)
                neg_item_id = self.sampler.sample_by_user_id(self.phase, uid, neg_sample_to - pos_num)
                neg_num = len(neg_item_id)

            neg_start = new_inter_num + pos_num
            neg_end = new_inter_num + pos_num + neg_num
            new_inter[uid_field][new_inter_num: neg_end] = uid
            new_inter[iid_field][new_inter_num: neg_start] = pos_item_id
            new_inter[iid_field][neg_start: neg_end] = neg_item_id
            new_inter[label_field][new_inter_num: neg_start] = 1
            new_inter_num += pos_num + neg_num

            if not self.real_time_neg_sampling and i % self.step == 0:
                if i == 0:
                    self.next = dict()
                    last_pr = 0
                else:
                    self.next[last_pr] = new_inter_num
                    last_pr = new_inter_num

        for field in [uid_field, iid_field, label_field]:
            new_inter[field] = new_inter[field][: new_inter_num]
        new_inter = pd.DataFrame(new_inter)
        if not self.real_time_neg_sampling:
            self.next[last_pr] = len(new_inter)
            return new_inter
        else:
            return self.dataset.join(new_inter)
