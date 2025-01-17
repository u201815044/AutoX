from .feature_engineer.fe_count import FeatureCount
from .feature_engineer.fe_stat import FeatureStat
from .feature_engineer.fe_rank import FeatureRank
from .feature_engineer.fe_nlp import FeatureNlp
from .feature_engineer.fe_time import FeatureTime
from .feature_engineer.fe_cumsum import FeatureCumsum
from .feature_engineer.fe_shift import FeatureShift
from .feature_engineer.fe_diff import FeatureDiff
from .feature_engineer.fe_one2M import FeatureOne2M
from .file_io.read_data import read_data_from_path
from .models.regressor import CrossLgbRegression, CrossXgbRegression, CrossTabnetRegression
from .models.classifier import CrossLgbBiClassifier, CrossXgbBiClassifier, CrossTabnetBiClassifier
from .process_data import feature_combination, train_test_divide, clip_label
from .process_data import feature_filter, auto_encoder
from .process_data.feature_type_recognition import Feature_type_recognition
from .util import log, reduce_mem_usage
from autox.feature_engineer import FeatureShiftTS, FeatureRollingStatTS, FeatureExpWeightedMean
from autox.models.regressor_ts import LgbRegressionTs, XgbRegressionTs

class AutoX():
    def __init__(self, target, train_name, test_name, path, time_series=False, ts_unit=None, time_col=None, metric='rmse', feature_type = {}, relations = [], id = [], task_type = 'regression', Debug = False):
        self.Debug = Debug
        self.info_ = {}
        self.info_['id'] = id
        self.info_['task_type'] = task_type
        self.info_['target'] = target
        self.info_['feature_type'] = feature_type
        self.info_['relations'] = relations
        self.info_['train_name'] = train_name
        self.info_['test_name'] = test_name
        self.info_['metric'] = metric
        self.info_['time_series'] = time_series
        self.info_['ts_unit'] = ts_unit
        self.info_['time_col'] = time_col
        self.dfs_ = read_data_from_path(path)
        if time_series:
            assert(ts_unit is not None)
            assert(time_col is not None)
        if Debug:
            log("Debug mode, sample data")
            self.dfs_[train_name] = self.dfs_[train_name].sample(5000)
        self.info_['max_target'] = self.dfs_[train_name][target].max()
        self.info_['min_target'] = self.dfs_[train_name][target].min()
        if feature_type == {}:
            for table_name in self.dfs_.keys():
                df = self.dfs_[table_name]
                feature_type_recognition = Feature_type_recognition()
                feature_type = feature_type_recognition.fit(df)
                self.info_['feature_type'][table_name] = feature_type
        self.join_simple_tables()
        self.concat_train_test()

        self.dfs_['FE_all'] = None
        self.sub = None

        # 识别任务类型
        if self.dfs_[self.info_['train_name']][self.info_['target']].nunique() == 2:
            self.info_['task_type'] = 'binary'
        else:
            self.info_['task_type'] = 'regression'

    def join_simple_tables(self):
        simple_relations = [x for x in self.info_['relations'] if x['type'] == '1-1' and x['related_to_main_table'] == 'true']
        for relation in simple_relations:
            left_table_name = relation['left_entity']
            right_table_name = relation['right_entity']
            left_on = relation['left_on']
            right_on = relation['right_on']
            if right_table_name in [self.info_['train_name'], self.info_['test_name']]:
                left_table_name, right_table_name = right_table_name, left_table_name
                left_on, right_on = right_on, left_on

            skip_name = right_on
            merge_table_name = right_table_name
            merge_table = self.dfs_[merge_table_name].copy()

            # rename
            merge_table.columns = [x if x in skip_name else merge_table_name + '__' + x for x in merge_table.columns]

            self.dfs_[left_table_name] = self.dfs_[left_table_name].merge(merge_table, left_on=left_on,
                                                                            right_on=right_on, how='left')
            if left_on != right_on:
                self.dfs_[left_table_name].drop(right_on, axis=1, inplace=True)

            del merge_table
            for key_ in self.info_['feature_type'][merge_table_name]:
                if key_ not in skip_name:
                    self.info_['feature_type'][left_table_name][merge_table_name + '__' + key_] = self.info_['feature_type'][merge_table_name][key_]

    def concat_train_test(self):
        self.info_['shape_of_train'] = len(self.dfs_[self.info_['train_name']])
        self.info_['shape_of_test'] = len(self.dfs_[self.info_['test_name']])
        self.dfs_['train_test'] = self.dfs_[self.info_['train_name']].append(self.dfs_[self.info_['test_name']])
        self.dfs_['train_test'].index = range(len(self.dfs_['train_test']))

        feature_type_train_test = {}
        for col in self.dfs_['train_test'].columns:
            if col in self.info_['feature_type'][self.info_['train_name']]:
                feature_type_train_test[col] = self.info_['feature_type'][self.info_['train_name']][col]
            else:
                feature_type_train_test[col] = self.info_['feature_type'][self.info_['test_name']][col]
        self.info_['feature_type']['train_test'] = feature_type_train_test

    def split_train_test(self):
        self.dfs_['FE_train'] = self.dfs_['FE_all'][:self.info_['shape_of_train']]
        self.dfs_['FE_test'] = self.dfs_['FE_all'][self.info_['shape_of_train']:]

    def get_submit(self):

        id_ = self.info_['id']
        target = self.info_['target']

        # 特征工程
        log("start feature engineer")
        df = self.dfs_['train_test']
        feature_type = self.info_['feature_type']['train_test']

        # 1-M拼表特征
        # one2M拼表特征
        log("feature engineer: one2M")
        featureOne2M = FeatureOne2M()
        featureOne2M.fit(self.info_['relations'], self.info_['train_name'], self.info_['feature_type'])
        log(f"featureOne2M ops: {featureOne2M.get_ops()}")
        if len(featureOne2M.get_ops()) != 0:
            self.dfs_['FE_One2M'] = featureOne2M.transform(df, self.dfs_)
        else:
            self.dfs_['FE_One2M'] = None
            log("ignore featureOne2M")

        # 时间特征
        log("feature engineer: time")
        featureTime = FeatureTime()
        featureTime.fit(df, df_feature_type=feature_type, silence_cols=id_ + [target])
        log(f"featureTime ops: {featureTime.get_ops()}")
        self.dfs_['FE_time'] = featureTime.transform(df)


        # cumsum特征
        log("feature engineer: Cumsum")
        featureCumsum = FeatureCumsum()
        featureCumsum.fit(df, df_feature_type=feature_type, silence_group_cols=id_ + [target],
                          silence_agg_cols=id_ + [target], select_all=False)
        fe_cumsum_cnt = 0
        for key_ in featureCumsum.get_ops().keys():
            fe_cumsum_cnt += len(featureCumsum.get_ops()[key_])
        if fe_cumsum_cnt < 30:
            self.dfs_['FE_cumsum'] = featureCumsum.transform(df)
            log(f"featureCumsum ops: {featureCumsum.get_ops()}")
        else:
            self.dfs_['FE_cumsum'] = None
            log("ignore featureCumsum")


        # shift特征
        log("feature engineer: Shift")
        featureShift = FeatureShift()
        featureShift.fit(df, df_feature_type=feature_type, silence_group_cols=id_ + [target],
                         silence_agg_cols=id_ + [target], select_all=False)
        fe_shift_cnt = 0
        for key_ in featureShift.get_ops().keys():
            fe_shift_cnt += len(featureShift.get_ops()[key_])
        if fe_shift_cnt < 30:
            self.dfs_['FE_shift'] = featureShift.transform(df)
            log(f"featureShift ops: {featureShift.get_ops()}")
        else:
            self.dfs_['FE_shift'] = None
            log("ignore featureShift")


        # diff特征
        log("feature engineer: Diff")
        featureDiff = FeatureDiff()
        featureDiff.fit(df, df_feature_type=feature_type, silence_group_cols=id_ + [target],
                        silence_agg_cols=id_ + [target], select_all=False)
        fe_diff_cnt = 0
        for key_ in featureDiff.get_ops().keys():
            fe_diff_cnt += len(featureDiff.get_ops()[key_])
        if fe_diff_cnt < 30:
            self.dfs_['FE_diff'] = featureDiff.transform(df)
            log(f"featureDiff ops: {featureDiff.get_ops()}")
        else:
            self.dfs_['FE_diff'] = None
            log("ignore featureDiff")


        # 统计特征
        log("feature engineer: Stat")
        featureStat = FeatureStat()
        featureStat.fit(df, df_feature_type=feature_type, silence_group_cols= id_ + [target],
                        silence_agg_cols= id_ + [target], select_all=False)

        fe_stat_cnt = 0
        for key_ in featureStat.get_ops().keys():
            fe_stat_cnt += len(featureStat.get_ops()[key_])
        if fe_stat_cnt < 1500:
            self.dfs_['FE_stat'] = featureStat.transform(df)
            log(f"featureStat ops: {featureStat.get_ops()}")
        else:
            self.dfs_['FE_stat'] = None
            log("ignore featureStat")

        # nlp特征
        log("feature engineer: NLP")
        featureNlp = FeatureNlp()
        featureNlp.fit(df, target, df_feature_type=feature_type, silence_cols=id_, select_all=False)
        self.dfs_['FE_nlp'] = featureNlp.transform(df)
        log(f"featureNlp ops: {featureNlp.get_ops()}")

        # count特征
        log("feature engineer: Count")
        # degree自动调整
        featureCount = FeatureCount()
        featureCount.fit(df, degree=2, df_feature_type=feature_type, silence_cols= id_ + [target], select_all=False)
        if len(featureCount.get_ops()) > 500:
            featureCount = FeatureCount()
            featureCount.fit(df, degree=1, df_feature_type=feature_type, silence_cols=id_ + [target], select_all=False)
        self.dfs_['FE_count'] = featureCount.transform(df)
        log(f"featureCount ops: {featureCount.get_ops()}")


        # rank特征
        log("feature engineer: Rank")
        featureRank = FeatureRank()
        featureRank.fit(df, df_feature_type=feature_type, select_all=False)
        fe_rank_cnt = 0
        for key_ in featureRank.get_ops().keys():
            fe_rank_cnt += len(featureRank.get_ops()[key_])
        if fe_rank_cnt < 500:
            self.dfs_['FE_rank'] = featureRank.transform(df)
            log(f"featureRank ops: {featureRank.get_ops()}")
        else:
            self.dfs_['FE_rank'] = None
            log("ignore featureRank")

        # auto_encoder
        df = auto_encoder(df, feature_type, id_)

        # 特征合并
        log("feature combination")
        df_list = [df, self.dfs_['FE_nlp'], self.dfs_['FE_count'], self.dfs_['FE_stat'], self.dfs_['FE_rank'], self.dfs_['FE_shift'], self.dfs_['FE_diff'], self.dfs_['FE_cumsum'], self.dfs_['FE_One2M']]
        self.dfs_['FE_all'] = feature_combination(df_list)

        # # 内存优化
        # self.dfs_['FE_all'] = reduce_mem_usage(self.dfs_['FE_all'])

        # train和test数据切分
        train_length = self.info_['shape_of_train']
        train, test = train_test_divide(self.dfs_['FE_all'], train_length)
        log(f"shape of FE_all: {self.dfs_['FE_all'].shape}, shape of train: {train.shape}, shape of test: {test.shape}")

        # 特征过滤
        log("feature filter")
        used_features = feature_filter(train, test, id_, target)
        log(f"used_features: {used_features}")

        # 模型训练
        log("start training model")
        if self.info_['task_type'] == 'regression':
            model_lgb = CrossLgbRegression(metric=self.info_['metric'])
            model_lgb.fit(train[used_features], train[target], tuning=False, Debug=self.Debug)

            model_xgb = CrossXgbRegression(metric=self.info_['metric'])
            model_xgb.fit(train[used_features], train[target], tuning=False, Debug=self.Debug)

            # model_tabnet = CrossTabnetRegression()
            # model_tabnet.fit(train[used_features], train[target], tuning=True, Debug=self.Debug)

        elif self.info_['task_type'] == 'binary':
            model_lgb = CrossLgbBiClassifier()
            model_lgb.fit(train[used_features], train[target], tuning=False, Debug=self.Debug)

            model_xgb = CrossXgbBiClassifier()
            model_xgb.fit(train[used_features], train[target], tuning=False, Debug=self.Debug)

            # model_tabnet = CrossTabnetBiClassifier()
            # model_tabnet.fit(train[used_features], train[target], tuning=True, Debug=self.Debug)

        # 特征重要性
        fimp = model_lgb.feature_importances_
        log("feature importance")
        log(fimp)

        # 模型预测
        predict_lgb = model_lgb.predict(test[used_features])
        predict_xgb = model_xgb.predict(test[used_features])
        # predict_tabnet = model_tabnet.predict(test[used_features])
        predict = (predict_xgb + predict_lgb) / 2

        # 预测结果后处理
        min_ = self.info_['min_target']
        max_ = self.info_['max_target']
        predict = clip_label(predict, min_, max_)

        # 获得结果
        sub = test[id_]
        sub[target] = predict
        sub.index = range(len(sub))

        return sub

    def get_submit_ts(self):

        id_ = self.info_['id']
        target = self.info_['target']

        # 特征工程
        log("start feature engineer")
        df = self.dfs_['train_test']
        feature_type = self.info_['feature_type']['train_test']

        # 1-M拼表特征
        # one2M拼表特征
        log("feature engineer: one2M")
        featureOne2M = FeatureOne2M()
        featureOne2M.fit(self.info_['relations'], self.info_['train_name'], self.info_['feature_type'])
        log(f"featureOne2M ops: {featureOne2M.get_ops()}")
        if len(featureOne2M.get_ops()) != 0:
            self.dfs_['FE_One2M'] = featureOne2M.transform(df, self.dfs_)
        else:
            self.dfs_['FE_One2M'] = None
            log("ignore featureOne2M")

        # 时间特征
        log("feature engineer: time")
        featureTime = FeatureTime()
        featureTime.fit(df, df_feature_type=feature_type, silence_cols=id_ + [target])
        log(f"featureTime ops: {featureTime.get_ops()}")
        self.dfs_['FE_time'] = featureTime.transform(df)

        # lag_ts特征
        log("feature engineer: ShiftTS")
        featureShiftTS = FeatureShiftTS()
        featureShiftTS.fit(df, id_, target, feature_type, self.info_['time_col'], self.info_['ts_unit'])
        log(f"featureShiftTS ops: {featureShiftTS.get_ops()}")
        log(f"featureShiftTS lags: {featureShiftTS.get_lags()}")
        self.dfs_['FE_shift_ts'] = featureShiftTS.transform(df)

        # rolling_stat_ts特征
        log("feature engineer: RollingStatTS")
        featureRollingStatTS = FeatureRollingStatTS()
        featureRollingStatTS.fit(df, id_, target, feature_type, self.info_['time_col'], self.info_['ts_unit'])
        log(f"featureRollingStatTS ops: {featureRollingStatTS.get_ops()}")
        log(f"featureRollingStatTS windows: {featureRollingStatTS.get_windows()}")
        self.dfs_['FE_rollingStat_ts'] = featureRollingStatTS.transform(df)

        # exp_weighted_mean_ts特征
        log("feature engineer: ExpWeightedMean")
        featureExpWeightedMean = FeatureExpWeightedMean()
        featureExpWeightedMean.fit(df, id_, target, feature_type, self.info_['time_col'], self.info_['ts_unit'])
        log(f"featureExpWeightedMean ops: {featureExpWeightedMean.get_ops()}")
        log(f"featureExpWeightedMean lags: {featureExpWeightedMean.get_lags()}")
        self.dfs_['FE_ewm'] = featureExpWeightedMean.transform(df)

        # label_encoder
        df = auto_encoder(df, feature_type, id_)

        # 特征合并
        log("feature combination")
        df_list = [df, self.dfs_['FE_One2M'], self.dfs_['FE_time'], self.dfs_['FE_shift_ts'], self.dfs_['FE_rollingStat_ts'], self.dfs_['FE_ewm']]
        self.dfs_['FE_all'] = feature_combination(df_list)

        # # 内存优化
        # self.dfs_['FE_all'] = reduce_mem_usage(self.dfs_['FE_all'])

        # train和test数据切分
        train_length = self.info_['shape_of_train']
        train, test = train_test_divide(self.dfs_['FE_all'], train_length)
        log(f"shape of FE_all: {self.dfs_['FE_all'].shape}, shape of train: {train.shape}, shape of test: {test.shape}")

        # 特征过滤
        log("feature filter")
        used_features = feature_filter(train, test, id_, target)
        log(f"used_features: {used_features}")

        # 模型训练
        log("start training model")
        if self.info_['task_type'] == 'regression':
            model_lgb = LgbRegressionTs()
            model_lgb.fit(train, test, used_features, target, self.info_['time_col'], self.info_['ts_unit'])

            #model_xgb = XgbRegressionTs()
            #model_xgb.fit(train, test, used_features, target, self.info_['time_col'], self.info_['ts_unit'])

        # 特征重要性
        fimp = model_lgb.feature_importances_
        log("feature importance")
        log(fimp)

        # 模型回溯
        train_lgb = model_lgb.predict(train, used_features)
        # train_xgb = model_xgb.predict(train, used_features)
        # predict_tabnet = model_tabnet.predict(test[used_features])
        #train_predict = (train_xgb + train_lgb) / 2
        train_predict = train_lgb
        
        # 获得回溯结果
        sub_train = train[id_ + [self.info_['time_col']]]
        sub_train[target] = train_predict
        sub_train.index = range(len(sub_train))

        # 模型预测
        predict_lgb = model_lgb.predict(test, used_features)
        # predict_xgb = model_xgb.predict(test, used_features)
        # predict_tabnet = model_tabnet.predict(test[used_features])
        #predict = (predict_xgb + predict_lgb) / 2
        predict = predict_lgb
        
        # 预测结果后处理
        min_ = self.info_['min_target']
        max_ = self.info_['max_target']
        predict = clip_label(predict, min_, max_)

        # 获得结果
        sub = test[id_ + [self.info_['time_col']]]
        sub[target] = predict
        sub.index = range(len(sub))

        return sub, sub_train
