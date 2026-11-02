"""Small raw-sequence models shared by current and historical research readers."""
from __future__ import annotations

import numpy as np
import torch
from torch import nn

from qount.research.market_state_sequence import fold_scale


class OHLCVGRU(nn.Module):
    def __init__(self,assets,hidden=32,channels=5):
        super().__init__()
        self.encoder=nn.GRU(channels,hidden,batch_first=True)
        self.asset=nn.Embedding(assets,4)
        self.head=nn.Sequential(nn.LayerNorm(hidden+4),nn.Dropout(.1),nn.Linear(hidden+4,3))

    def forward(self,sequence,asset):
        _,h=self.encoder(sequence)
        return self.head(torch.cat((h[-1],self.asset(asset)),dim=1))


def forecast(model,x,asset):
    model.eval();parts=[]
    with torch.no_grad():
        for start in range(0,len(x),1024):
            parts.append(model(x[start:start+1024],asset[start:start+1024]).softmax(1).numpy())
    return .99*np.concatenate(parts)+.01/3


def fit_gru(sequence,asset,y,train,test,*,assets,epochs,seed):
    torch.manual_seed(seed)
    mean,scale=fold_scale(sequence[train])
    train_x=torch.from_numpy(np.ascontiguousarray((sequence[train]-mean)/scale))
    test_x=torch.from_numpy(np.ascontiguousarray((sequence[test]-mean)/scale))
    train_a=torch.from_numpy(asset[train]);test_a=torch.from_numpy(asset[test]);target=torch.from_numpy(y[train].astype(np.int64))
    model=OHLCVGRU(assets,channels=sequence.shape[-1]);prior=np.bincount(y[train],minlength=3)/len(train)
    if np.any(prior<=0):raise ValueError('all_three_states_required_in_training_fold')
    with torch.no_grad():model.head[-1].bias.copy_(torch.tensor(np.log(prior),dtype=torch.float32))
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.001)
    generator=torch.Generator().manual_seed(seed);history=[]
    for epoch in range(epochs):
        model.train();total=0.;count=0
        for batch in torch.randperm(len(train),generator=generator).split(256):
            optimizer.zero_grad(set_to_none=True)
            loss=nn.functional.cross_entropy(model(train_x[batch],train_a[batch]),target[batch])
            if not torch.isfinite(loss):raise RuntimeError('nonfinite_gru_loss')
            loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step();total+=float(loss.detach())*len(batch);count+=len(batch)
        history.append(total/count)
    return forecast(model,test_x,test_a),dict(training_cross_entropy=history,
        train_prediction=forecast(model,train_x,train_a),parameters=sum(p.numel() for p in model.parameters())),dict(
        model=model.state_dict(),mean=mean,scale=scale,hidden=32,assets=assets,input_channels=sequence.shape[-1])

