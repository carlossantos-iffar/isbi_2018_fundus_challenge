import multiprocessing
import threading
import Queue
from uuid import uuid4
import numpy as np
import SharedArray

import utils

img_h, img_w = 640, 640
n_grade_dr, n_grade_dme = 5, 3


def balance_per_class_indices(y, weights):
    weights = np.array(weights, dtype=float)
    p = np.zeros(len(y))
    for i, weight in enumerate(weights):
        p[y == i] = weight
    return np.random.choice(np.arange(len(y)), size=len(y), replace=True,
                            p=np.array(p) / p.sum())


def load_shared(args):
    i, array_fundus_rescale, array_fundus_rescale_mean_subtract, fundus, is_train = args
    array_fundus_rescale = SharedArray.attach(array_fundus_rescale)
    array_fundus_rescale_mean_subtract = SharedArray.attach(array_fundus_rescale_mean_subtract)
    array_fundus_rescale[i], array_fundus_rescale_mean_subtract[i] = utils.load_augmented([fundus], is_train)

    
class BatchIterator(object):

    def __init__(self, batch_size):
        self.batch_size = batch_size

    def __call__(self, fundus, grade):
        self.fundus, self.grade = fundus, grade
        return self

    def __iter__(self):
        n_samples = self.fundus.shape[0]
        bs = self.batch_size
        for i in range((n_samples + bs - 1) // bs):
            sl = slice(i * bs, (i + 1) * bs)
            fundus = self.fundus[sl]
            grade = self.grade[sl]
            yield self.transform(fundus, grade)


class QueueIterator(BatchIterator):

    def __iter__(self):
        queue = Queue.Queue(maxsize=20)
        end_marker = object()

        def producer():
            for fundus_fns, fundus_rescale, fundus_rescale_mean_subtract, grade in super(QueueIterator, self).__iter__():
                queue.put((np.array(fundus_fns), np.array(fundus_rescale), np.array(fundus_rescale_mean_subtract), np.array(grade)))
            queue.put(end_marker)

        thread = threading.Thread(target=producer)
        thread.daemon = True
        thread.start()

        item = queue.get()
        while item is not end_marker:
            yield item
            queue.task_done()
            item = queue.get()


class SharedIterator(QueueIterator):

    def __init__(self, *args):
        self.pool = multiprocessing.Pool()
        super(SharedIterator, self).__init__(*args)

    def transform(self, fundus, grade):
        shared_array_fundus_rescale_name = str(uuid4())
        shared_array_fundus_rescale_mean_subtract_name = str(uuid4())
        
        try:
            shared_array_fundus_mean_subt = SharedArray.create(
                shared_array_fundus_rescale_name, [len(fundus), img_h, img_w, 3], dtype=np.float32)
            shared_array_fundus_z = SharedArray.create(
                shared_array_fundus_rescale_mean_subtract_name, [len(fundus), img_h, img_w, 3], dtype=np.float32)
            
            args = []
            for i, _ in enumerate(fundus):
                args.append((i, shared_array_fundus_rescale_name, shared_array_fundus_rescale_mean_subtract_name, fundus[i], self.is_train))

            self.pool.map(load_shared, args)
            fundus_rescale = np.array(shared_array_fundus_mean_subt, dtype=np.float32)
            fundus_rescale_mean_subtract = np.array(shared_array_fundus_z, dtype=np.float32)
        finally:
            SharedArray.delete(shared_array_fundus_rescale_name)
            SharedArray.delete(shared_array_fundus_rescale_mean_subtract_name)

        return fundus, fundus_rescale, fundus_rescale_mean_subtract, grade


class TrainBatchFetcher(SharedIterator):

    def __init__(self, training_set, batch_size, class_weight):
        self.fundus_ori, self.grade_ori = training_set
        self.is_train = True
        self.class_weight = class_weight
        super(TrainBatchFetcher, self).__init__(batch_size)

    def __call__(self):
        indices = balance_per_class_indices(self.grade_ori, weights=self.class_weight)
        fundus = self.fundus_ori[indices]
        grade = self.grade_ori[indices]
        return super(TrainBatchFetcher, self).__call__(fundus, grade)


class ValidationBatchFetcher(SharedIterator):

    def __init__(self, validation_set, batch_size):
        self.fundus_ori, self.grade_ori = validation_set
        self.is_train = False
        super(ValidationBatchFetcher, self).__init__(batch_size)

    def __call__(self):
        return super(ValidationBatchFetcher, self).__call__(self.fundus_ori, self.grade_ori)

