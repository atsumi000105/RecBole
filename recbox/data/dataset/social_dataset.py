# @Time   : 2020/9/3
# @Author : Yupeng Hou
# @Email  : houyupeng@ruc.edu.cn

# UPDATE:
# @Time   : 2020/9/16, 2020/9/15, 2020/9/22
# @Author : Yupeng Hou, Xingyu Pan, Yushuo Chen
# @Email  : houyupeng@ruc.edu.cn, panxy@ruc.edu.cn, chenyushuo@ruc.edu.cn

import os

import numpy as np
from scipy.sparse import coo_matrix

from recbox.data.dataset import Dataset
from recbox.utils import FeatureSource


class SocialDataset(Dataset):
    def __init__(self, config, saved_dataset=None):
        super().__init__(config, saved_dataset=saved_dataset)

    def _get_field_from_config(self):
        super()._get_field_from_config()

        self.source_field = self.config['SOURCE_ID_FIELD']
        self.target_field = self.config['TARGET_ID_FIELD']
        self._check_field('source_field', 'target_field')

        self.logger.debug('source_id_field: {}'.format(self.source_field))
        self.logger.debug('target_id_field: {}'.format(self.target_field))

    def _load_data(self, token, dataset_path):
        super()._load_data(token, dataset_path)
        self.net_feat = self._load_net(self.dataset_name, self.dataset_path)

    def _build_feat_list(self):
        return [feat for feat in [self.inter_feat, self.user_feat, self.item_feat, self.net_feat] if feat is not None]

    def _load_net(self, dataset_name, dataset_path): 
        net_file_path = os.path.join(dataset_path, '{}.{}'.format(dataset_name, 'net'))
        if os.path.isfile(net_file_path):
            net_feat = self._load_feat(net_file_path, FeatureSource.NET)
            if net_feat is None:
                raise ValueError('.net file exist, but net_feat is None, please check your load_col')
            return net_feat
        else:
            raise ValueError('File {} not exist'.format(net_file_path))
            
    def _get_fields_in_same_space(self):
        fields_in_same_space = super()._get_fields_in_same_space()
        fields_in_same_space = [_ for _ in fields_in_same_space if (self.source_field not in _) and
                                                                   (self.target_field not in _)]
        for field_set in fields_in_same_space:
            if self.uid_field in field_set:
                field_set.update({self.source_field, self.target_field})

        return fields_in_same_space

    def _create_dgl_net_graph(self):
        import dgl
        net_tensor = self._dataframe_to_interaction(self.net_feat)
        source = net_tensor[self.source_field]
        target = net_tensor[self.target_field]
        ret = dgl.graph((source, target))
        for k in net_tensor:
            if k not in [self.source_field, self.target_field]:
                ret.edata[k] = net_tensor[k]
        return ret

    def net_matrix(self, form='coo', value_field=None):
        if form in ['coo', 'csr']:
            sids = self.net_feat[self.source_field].values
            tids = self.net_feat[self.target_field].values
            if value_field is None:
                data = np.ones(len(self.net_feat))
            else:
                if value_field not in self.field2source:
                    raise ValueError('value_field [{}] not exist.'.format(value_field))
                if self.field2source[value_field] != FeatureSource.NET:
                    raise ValueError('value_field [{}] can only be one of the net features'.format(value_field))
                data = self.net_feat[value_field].values
            mat = coo_matrix((data, (sids, tids)), shape=(self.user_num, self.user_num))
            if form == 'coo':
                return mat
            elif form == 'csr':
                return mat.tocsr()
        elif form == 'dgl':
            return self._create_dgl_net_graph()
        else:
            raise NotImplementedError('net matrix format [{}] has not been implemented.')

    def __str__(self):
        info = [super().__str__(),
                'The number of connections of social network: {}'.format(len(self.net_feat))]
        return '\n'.join(info)
