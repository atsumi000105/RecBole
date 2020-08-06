# @Time   : 2020/7/10
# @Author : Yupeng Hou
# @Email  : houyupeng@ruc.edu.cn

# UPDATE
# @Time    : 2020/8/5
# @Author  : Yupeng Hou
# @email   : houyupeng@ruc.edu.cn

class Interaction(object):
    def __init__(self, interaction):
        self.interaction = interaction
        for k in self.interaction:
            self.length = self.interaction[k].shape[0]
            break

    def __getitem__(self, index):
        if isinstance(index, str):
            return self.interaction[index]
        else:
            ret = {}
            for k in self.interaction:
                ret[k] = self.interaction[k][index]
            return Interaction(ret)

    def __len__(self):
        return self.length

    def to(self, device, selected_field=None):
        ret = {}
        try:
            selected_field = set(selected_field)
            for k in self.interaction:
                if k in selected_field:
                    ret[k] = self.interaction[k].to(device)
                else:
                    ret[k] = self.interaction[k]
        except:
            for k in self.interaction:
                ret[k] = self.interaction[k].to(device)
        return Interaction(ret)

    def cpu(self):
        ret = {}
        for k in self.interaction:
            ret[k] = self.interaction[k].cpu()
        return Interaction(ret)

    def numpy(self):
        ret = {}
        for k in self.interaction:
            ret[k] = self.interaction[k].numpy()
        return Interaction(ret)

    def repeat(self, *sizes):
        ret = {}
        for k in self.interaction:
            ret[k] = self.interaction[k].repeat(sizes)
        return Interaction(ret)

    def to_device_repeat_interleave(self, device, repeats):
        ret = {}
        for k in self.interaction:
            ret[k] = self.interaction[k].to(device).repeat_interleave(repeats)
        return Interaction(ret)

    def update(self, new_inter):
        for k in new_inter.interaction:
            self.interaction[k] = new_inter.interaction[k]
