import csv
import math
import os
import pickle

import numpy as np
from tqdm import tqdm

from chemprop.args import SklearnPredictArgs
from chemprop.data.utils import get_data, get_task_names
from chemprop.features import get_features_generator
from chemprop.sklearn_train import predict
from chemprop.utils import makedirs


def predict_sklearn(args: SklearnPredictArgs):

    if args.parcel_size and args.max_data_size:
        num_iterations = math.ceil(args.max_data_size/args.parcel_size)
        max_data_size = args.parcel_size
    else:
        num_iterations = 1
        max_data_size = args.max_data_size
    offset = 0

    for iteration in range(num_iterations):

        if iteration > 0:
            offset = offset + args.parcel_size
            max_data_size = max_data_size + args.parcel_size

        print('Loading data')
        data = get_data(path=args.test_path,
            smiles_column=args.smiles_column,
            target_columns=[],
            max_data_size=max_data_size,
            data_offset=offset
        )

        print('Computing morgan fingerprints')
        morgan_fingerprint = get_features_generator('morgan')
        for datapoint in tqdm(data, total=len(data)):
            datapoint.set_features(morgan_fingerprint(mol=datapoint.smiles, radius=args.radius, num_bits=args.num_bits))

        print(f'Predicting with an ensemble of {len(args.checkpoint_paths)} models')
        sum_preds = np.zeros((len(data), args.num_tasks))

        for checkpoint_path in tqdm(args.checkpoint_paths, total=len(args.checkpoint_paths)):
            with open(checkpoint_path, 'rb') as f:
                model = pickle.load(f)

            model_preds = predict(
                model=model,
                model_type=args.model_type,
                dataset_type=args.dataset_type,
                features=data.features()
            )
            sum_preds += np.array(model_preds)

        # Ensemble predictions
        avg_preds = sum_preds / len(args.checkpoint_paths)
        avg_preds = avg_preds.tolist()

        print(f'Saving predictions to {args.preds_path}')
        assert len(data) == len(avg_preds)
        makedirs(args.preds_path, isfile=True)

        # Copy predictions over to data
        task_names = get_task_names(path=args.test_path)
        for datapoint, preds in zip(data, avg_preds):
            for pred_name, pred in zip(task_names, preds):
                datapoint.row[pred_name] = pred

        # Save
        if iteration != 0:
            name, ext = os.path.splitext(args.preds_path)
            preds_path  = "{name}.{it}{ext}".format(name=name, it=iteration, ext=ext)
        else:
            preds_path = args.preds_path
        with open(args.preds_path, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].row.keys())
            writer.writeheader()

            for datapoint in data:
                writer.writerow(datapoint.row)
