# coding=utf-8
import sys
import os
import datetime
import pickle
import json
import logging
import pandas

from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import RFECV
from sklearn.model_selection import RandomizedSearchCV
from imblearn.under_sampling import RandomUnderSampler
from sklearn import preprocessing, __version__

from util import DigDogUtils
from util.DigDogParser import DigDogLearnParser
import DigDogConfig


class QuincyLearn(object):

    def __init__(self, path_to_csv, classifier, feature_selection, undersampling, compress_model=True, scaling=False):
        self._path_to_csv = path_to_csv
        self._classifier = classifier
        self._feature_selection = feature_selection
        self._undersampling = undersampling
        self._compress_model = compress_model
        self._scaling = scaling

    def learn(self):
        X, y = self.__get_data()
        feature_names = list(X.columns.values)
        if self._undersampling:
            X, y = self.__undersample(feature_names, X, y)

        if self._feature_selection:
            X = self.__select_features(X, y, feature_names)

        if self._scaling:
            logging.info("处理中...")
            X = preprocessing.scale(X)

        rgs = RandomizedSearchCV(estimator=self._classifier[1], param_distributions=self._classifier[2],
                                 error_score=0, cv=DigDogConfig.CV, n_iter=DigDogConfig.ITERS, refit=True,
                                 n_jobs=-1, scoring=DigDogConfig.METRIC, iid=False)
        rgs.fit(X, y)
        logging.info("Best SCORE: %s" % str(rgs.best_score_))
        logging.info("Best Params: %s" % str(rgs.best_params_))
        self._optimized_model = rgs

    def __undersample(self, feature_names, X, y):
        logging.info("随机欠采样中...")
        undersampler = RandomUnderSampler(ratio=DigDogConfig.RATIO)
        X, y = undersampler.fit_sample(X, y)
        X = pandas.DataFrame(X, columns=feature_names)
        return X, y

    def __select_features(self, X, y, feature_names):
        logging.info("[基于RandomForest]自动提取特征值中...")

        model = RandomForestClassifier(n_jobs=-1)
        rfe = RFECV(model, cv=DigDogConfig.CV, scoring=DigDogConfig.METRIC)
        fit = rfe.fit(X, y)
        logging.info("特征选择数量: %d" % fit.n_features_)

        discarded, selected = self.__get_discarded_and_selected_features(feature_names, fit)

        X = self.__drop_discarded_features(X, discarded)

        feature_selection_results = self.__get_feature_selection_results(X, discarded, feature_names, fit, model,
                                                                         selected, y)
        self._featureSelectionResults = feature_selection_results
        return X

    def __get_feature_selection_results(self, X, discarded, feature_names, fit, model, selected, y):
        feature_selection_results = {"grid_scores": list(fit.grid_scores_),
                                     "selected": selected,
                                     "discarded": discarded,
                                     "feature_importance": zip(feature_names, map(lambda x: round(x * 100, 3),
                                                                                  model.fit(X,
                                                                                            y).feature_importances_))}
        return feature_selection_results

    def __drop_discarded_features(self, X, discarded):
        for discarded_feature in discarded:
            X = X.drop(discarded_feature, 1)
        return X

    def __get_discarded_and_selected_features(self, feature_names, fit):
        discarded = []
        selected = []
        for feat in zip(feature_names, fit.support_):
            if feat[1]:
                selected.append(feat[0])
            else:
                discarded.append(feat[0])
        return discarded, selected

    def __get_data(self):
        logging.info("加载数据集中...")
        data = pandas.read_csv(self._path_to_csv)  # , compression="bz2")
        data = pandas.DataFrame(data).fillna(method="ffill")
        # DataFrame is one data structure in package pandas, which representing multidimensional ayyarys
        # fillna method is used to fulfill the lost data
        y = data.ground_truth

        # DataFrame.drop() method is used to move out targeted rows or columns
        # parameters: labels, axis(0 or 'index', 1 or 'column'), index, colunms, level, inplace, errors
        data = data.drop('ground_truth', 1)
        if 'malfind' in data:
            data = data.drop('malfind', 1)
        if 'hollowfind' in data:
            data = data.drop('hollowfind', 1)
        X = data.drop('vad', 1)

        return X, y

    def store(self, model_out_path, model_name):
        filename = os.path.join(model_out_path, model_name + ".model")
        pickled_model = pickle.dumps(self._optimized_model.best_estimator_)

        if self._compress_model:
            pickled_model = pickled_model.encode("zlib")

        with open(filename, "wb") as f:
            f.write(pickled_model)

        model_description_filename = os.path.join(model_out_path, model_name + ".json")
        model_desciption_file = open(model_description_filename, "w")

        model_description = {}
        model_description["model_name"] = model_name
        model_description["creation_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        model_description["classifier"] = {"classifier": self._classifier[0], "param_space": str(self._classifier[2])}
        model_description["model_params"] = self._optimized_model.best_params_
        model_description["scaling"] = self._scaling
        model_description["metric"] = DigDogConfig.METRIC
        if self._feature_selection:
            model_description["feature_selection_results"] = self._featureSelectionResults

        json.dump(model_description, model_desciption_file)
        model_desciption_file.close()


def main():
    parser = DigDogLearnParser()
    arguments = parser.parse(sys.argv[1:])
    DigDogUtils.set_up_logging(arguments["verbose"])

    classifier = None
    for clf in DigDogConfig.CLASSIFIERS:
        if clf[0] == arguments["classifier"]:
            classifier = clf
            break
    if classifier is None:
        raise Exception("Classifier %s unknown!" % arguments["classifier"])

    quincy_learn = QuincyLearn(path_to_csv=arguments["csv"],
                               classifier=classifier,
                               feature_selection=arguments["feature_selection"],
                               undersampling=arguments["undersampling"],
                               scaling=arguments["scaling"])
    quincy_learn.learn()
    quincy_learn.store(arguments["model_outpath"], arguments["model_name"])


if __name__ == "__main__":
    print('The scikit-learn version is {}.'.format(__version__))
    main()
