from time import time as time
import numpy as np
from tqdm import tqdm

import torch
from torch.autograd import Variable
import torch.utils.data
from torch import nn as nn

import torchvision.utils as vutils
from torchvision.utils import make_grid

from tensorboardX import SummaryWriter


class Options:
    def __init__(self):
        self.cuda = False
        self.batch_size = 256
        self.nz = 2
        self.num_iter = 50
        self.num_disc_iters = 10
        self.wgangp_lambda = 0.1
        self.visualize_nth = 10
        self.n_classes = 4
        self.n_classes1 = 41
        self.n_classes2 = 35
        self.conditional = False
        self.shuffle_labels = False
        self.checkpoints = []
        self.path = ''
        self.two_labels = False
        self.test_labels = False
        

TENSORBOARD = True

DATASET = 'MNIST' # 'MNIST', 'gaussians'

class GAN_base():
    def __init__(self, netG, netD, optimizerD, optimizerG, opt):
        self.netD, self.netG = netD, netG
        self.optimizerD, self.optimizerG = optimizerD, optimizerG

        self.opt = opt

        if self.opt is not None and self.opt.cuda:
            if self.netD is not None:
                self.netD.cuda()
            if self.netG is not None:
                self.netG.cuda()


    def compute_disc_score(self, data_a, data_b):
        raise NotImplementedError
        errD = None
        return errG


    def compute_gen_score(self, data):
        raise NotImplementedError
        errD = None
        return errD


    def train_D_one_step(self, iterator_a, iterator_b):
        self.netD.zero_grad()
        for p in self.netD.parameters():
            p.requires_grad = True  # to avoid computation

        # get data and scores
        data_a = next(iterator_a)
        data_b = next(iterator_b)

        errD = self.compute_disc_score(data_a, data_b)
        
        errD = errD.mean()
        errD.backward()
        self.optimizerD.step()
        return errD.data[0], data_a, data_b


    def train_G_one_step(self, iterator_fake, fake_images=None):
        self.netG.zero_grad()
        for p in self.netD.parameters():
            p.requires_grad = False  # to avoid computation

        if fake_images is None:
            fake_images = next(iterator_fake)
        errG = self.compute_gen_score(fake_images)

        try:
            errG.backward()
            self.optimizerG.step()
        except:
            pass
        return errG.data[0], fake_images


    def train_one_step(self, iterator_data, iterator_fake, num_disc_iters=1, i_iter=None):
        fake_images, errD, errG = None, None, None
        # Update D network
        for i in range(num_disc_iters):
            errD, real_data, fake_images = self.train_D_one_step(iterator_data, iterator_fake)
        # Update G network
        errG, fake_images = self.train_G_one_step(iterator_fake, fake_images)
        return errD, errG


    def train(self, data_iter, opt=None, logger=None, callback=None):
        if opt is not None:
            self.opt = opt

        if TENSORBOARD:
            writer = SummaryWriter(opt.path)

        netD, netG = self.netD, self.netG

        netD.train()
        netG.train()

        # move everything on a GPU
        if self.opt.cuda:
            netD.cuda()
            netG.cuda()

        # iterators
        iterator_data = data_iter   
        iterator_fake = self.fake_data_generator(opt.batch_size, opt.nz, iterator_data)

        gen_score_history = []
        disc_score_history = []

        # main loop
        t_start = time()
        time_history = []

        for i_iter in tqdm(range(opt.num_iter)):

            if (i_iter + 1) in self.opt.checkpoints:
                self.save(i_iter + 1)

            errD, errG = self.train_one_step(iterator_data, iterator_fake,
                                             num_disc_iters=opt.num_disc_iters, i_iter=i_iter)

            if TENSORBOARD:
                writer.add_scalar('disc_loss', errD, i_iter)
                writer.add_scalar('gen_loss', errG, i_iter)

            if logger is not None:
                logger.add('disc_loss', errD, i_iter)
                logger.add('gen_loss', errG, i_iter)

            if callback is not None:
                callback(self, i_iter)

            gen_score_history.append(errG)
            disc_score_history.append(errD)
            time_history.append(time() - t_start)

            np.save(self.opt.path + 'loss.pkl', np.asarray([self.opt.visualize_nth] + gen_score_history + disc_score_history + time_history))
                
        if TENSORBOARD:
            writer.close()

        self.save('final')


    def save(self, tag):
        if self.netG is not None:
            torch.save(self.netG.state_dict(), self.opt.path + 'gen_{}.pth'.format(tag))
        if self.netD is not None:
            torch.save(self.netD.state_dict(), self.opt.path + 'disc_{}.pth'.format(tag))


    def join_xy(self, batch):
        th = torch.cuda if self.opt.cuda else torch

        x, y = batch

        if len(x.size()) == 2:
            y_onehot = th.FloatTensor(x.size()[0], self.opt.n_classes)
            y_onehot.zero_()
            y_onehot.scatter_(1, y.data.view(-1,1), 1)

            return torch.cat((x, torch.autograd.Variable(y_onehot)), 1)

        if len(x.size()) == 4:
            y_onehot = th.FloatTensor(x.size()[0], self.opt.n_classes)
            y_onehot.zero_()

            y_onehot.scatter_(1, y.data.view(-1,1), 1)
            y_onehot = y_onehot.view(x.size()[0], self.opt.n_classes, 1, 1)

            return torch.cat((x, torch.autograd.Variable(y_onehot.expand(x.size()[0], self.opt.n_classes, x.size()[2], x.size()[3]))), 1)


    def gen_labels(self, batch_size, n_classes=None):
        if n_classes is None:
            n_classes = self.opt.n_classes

        th = torch.cuda if self.opt.cuda else torch
        if self.opt.cuda:
            return torch.autograd.Variable(torch.LongTensor(batch_size).random_(0, n_classes).cuda())
        else:
            return torch.autograd.Variable(torch.LongTensor(batch_size).random_(0, n_classes))


    def gen_latent_noise(self, batch_size, nz):
        th = torch.cuda if self.opt.cuda else torch
        shape = [batch_size] + list(nz)
        if self.opt.cuda:
            return torch.zeros(shape).normal_(0, 1).cuda()
        else:
            return torch.zeros(shape).normal_(0, 1)


    def gen_fake_data(self, batch_size, nz, noise=None, label=None, drop_labels=False):
        if noise is None:
            noise = Variable(self.gen_latent_noise(batch_size, nz))

        if self.opt.two_labels:
            y1 = self.gen_labels(batch_size, self.opt.n_classes1)
            y2 = self.gen_labels(batch_size, self.opt.n_classes2)
            return self.netG(noise, y1, y2), y1, y2


        if self.opt.conditional:
            if label is None:
                y = self.gen_labels(batch_size)
            else:
                y = torch.autograd.Variable(torch.LongTensor(batch_size).zero_() + label)
                if self.opt.cuda:
                    y = y.cuda()

            noise = self.join_xy((noise, y))
            
            if drop_labels:
                return self.netG(noise)
            else:
                return self.netG(noise), y

        return self.netG(noise)


    def fake_data_generator(self, batch_size, nz, iterator_data, selected=None, drop_labels=False):
        if self.opt.shuffle_labels:
            i = 0
            while True:
                i = 1 - i
                if i:
                    yield self.gen_fake_data(batch_size, nz)
                else:
                    x, y = next(iterator_data)

                    shift = torch.from_numpy(np.random.randint(1, self.opt.n_classes, size=y.size()))
                    if self.opt.cuda:
                        shift = shift.cuda()
                    
                    y = torch.autograd.Variable(torch.remainder(y.data + shift, self.opt.n_classes))
                    
                    a, b = self.gen_fake_data(batch_size, nz)
                    
                    yield (x,y)

        else:
            while True:
                yield self.gen_fake_data(batch_size, nz, label=selected, drop_labels=drop_labels)


class GAN(GAN_base):
    def __init__(self, netG, netD, optimizerD, optimizerG, opt):
        GAN_base.__init__(self, netG, netD, optimizerD, optimizerG, opt)

        # criterion for training
        self.criterion = torch.nn.BCEWithLogitsLoss(size_average=True)
        self.real_label = 1
        self.fake_label = 0
        self.generator_label = 1  # fake labels are real for generator cost


    def compute_disc_score(self, data_a, data_b):
        th = torch.cuda if self.opt.cuda else torch


        if type(data_a) == list or type(data_a) == tuple:
            data_a = (data_a[0].detach(),) + tuple(a for a in data_a[1:])
            data_b = (data_b[0].detach(),) + tuple(b for b in data_b[1:])
            # data_b = [data_b[0].detach(), data_b[1], data_b[2]]

        # if type(data_a) == list:
        #     data_a = [data_a[0].detach(), data_a[1], data_a[2]]
        #     data_b = [data_b[0].detach(), data_b[1], data_b[2]]

        # elif type(data_a) == tuple:
        #     data_a = data_a[0].detach(), data_a[1]
        #     data_b = data_b[0].detach(), data_b[1]
        else:
            data_a = data_a.detach()
            data_b = data_b.detach()

        if self.opt.conditionalD:
            data_a = self.join_xy(data_a)
            data_b = self.join_xy(data_b)

        if type(data_a) == list or type(data_a) == tuple:
            scores_a = self.netD(*data_a)
            scores_b = self.netD(*data_b)
        else:
            scores_a = self.netD(data_a)
            scores_b = self.netD(data_b)

        if type(scores_a) is tuple:
            labels_a = Variable(th.FloatTensor(scores_a[0].size(0)).fill_(self.real_label))
            errD_a = self.criterion(scores_a[0], labels_a) + self.criterion(scores_a[1], labels_a)
        else:
            labels_a = Variable(th.FloatTensor(scores_a.size(0)).fill_(self.real_label))
            errD_a = self.criterion(scores_a, labels_a)

        if type(scores_b) is tuple:
            labels_b = Variable(th.FloatTensor(scores_b[0].size(0)).fill_(self.fake_label))
            errD_b = self.criterion(scores_b[0], labels_b) + self.criterion(scores_b[1], labels_b)
        else:
            labels_b = Variable(th.FloatTensor(scores_b.size(0)).fill_(self.fake_label))
            errD_b = self.criterion(scores_b, labels_b)
        
        errD = errD_a + errD_b
        return errD


    def compute_gen_score(self, data):
        th = torch.cuda if self.opt.cuda else torch

        if self.opt.conditionalD:
            data = self.join_xy(data)

        if type(data) == list or type(data) == tuple:
            scores = self.netD(*data)
        else:
            scores = self.netD(data)

        if type(scores) is tuple:
            labels = Variable(th.FloatTensor(scores[0].size()).fill_(self.generator_label))
            errG = self.criterion(scores[0], labels) + self.criterion(scores[1], labels)
        else:
            labels = Variable(th.FloatTensor(scores.size()).fill_(self.generator_label))
            errG = self.criterion(scores, labels)

        return errG
