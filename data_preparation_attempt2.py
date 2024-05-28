
import pandas as pd
import re
from pandas.tseries.offsets import MonthEnd
#from scipy.stats import shapiro
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from typing import NamedTuple
import data_preparation_utils as prep_utils
from typing import NamedTuple

def download_dataset():
    prep_utils.download_kaggle_competition_dataset('./.kaggle/kaggle.json', 'store-sales-time-series-forecasting', './dataset')



class TimeSeriesForecastDataframes(NamedTuple):
    base_xy_df: pd.DataFrame
    stores_df: pd.DataFrame
    oil_df: pd.DataFrame
    transactions_df: pd.DataFrame
    special_days_df: pd.DataFrame

def get_feature_dfs() ->TimeSeriesForecastDataframes:
    """Get dataframes containing all the info in the dataset.
    train_xy_base_df: The dataframe containing most features(x), and the Y value (sales). Base because other features should be merged into it.
    Note that the only features that will be provided for prediction are the ones in train_xy_base, but since most entities should already exist, so you have the data, it should still improve predictions to use the other dfs.
    """
    train_xy_base_df = pd.read_csv('./dataset/train.csv', index_col='id')
    stores_df = pd.read_csv('./dataset/stores.csv', index_col='store_nbr')
    oil_df = pd.read_csv('./dataset/oil.csv') 
    transactions_df = pd.read_csv('./dataset/transactions.csv')
    holiday_events_df = pd.read_csv('./dataset/holidays_events.csv')
    #elements_to_predict_x_base_df = pd.read_csv('./dataset/test.csv', index_col='id')
    #sample_submission_df = pd.read_csv('./dataset/sample_submission.csv')
    return TimeSeriesForecastDataframes(train_xy_base_df, stores_df, oil_df, transactions_df, holiday_events_df)

class AdditionalDataframes(NamedTuple):
    elements_to_predict_x_base_df: pd.DataFrame
    sample_submission_df: pd.DataFrame

def get_additional_dfs()->AdditionalDataframes:
    elements_to_predict_x_base_df = pd.read_csv('./dataset/test.csv', index_col='id')
    sample_submission_df = pd.read_csv('./dataset/sample_submission.csv')
    return AdditionalDataframes(elements_to_predict_x_base_df,sample_submission_df)



def rename_raw_dfs_cols(dfs:TimeSeriesForecastDataframes) ->TimeSeriesForecastDataframes:
    """Rename the columns of the raw dataframes so they are more easily understandable
       Please note that while usually its a good idea to require the raw values as parameters instead of a dataclass to provide more flexibility
       Here we need to have a single variable, the input X as parameter, since this method will be part of the scikitlearn pipeline.
       And so we use a dataclass instead.
    """
    base_xy_df = dfs.base_xy_df.rename(columns={'family':'product_family', 'onpromotion':'products_of_family_on_promotion'})
    oil_df = dfs.oil_df.rename(columns={'dcoilwtico':'oil_price'})
    stores_df = dfs.stores_df.rename(columns={'type':'store_type', 'cluster':'store_cluster', 'city':'store_city', 'state':'store_state'})
    transactions_df = dfs.transactions_df.rename(columns={'transactions':'all_products_transactions'})
    special_days_df = dfs.special_days_df.rename(columns={'type':'day_type', 'locale':'special_day_locale_type', 'locale_name':'special_day_locale','description':'special_day_reason', 'transferred':'special_day_transferred'})

    return TimeSeriesForecastDataframes(base_xy_df, stores_df, oil_df, transactions_df, special_days_df)

def merge_data_sources(dfs:TimeSeriesForecastDataframes)->pd.DataFrame:
    """Add relevant columns from the auxiliary dataframes into a features dataset, be it the train set or the test set.
       Please note that while usually its a good idea to have the required variables as parameters instead of a dataclass to provide more flexibility
       Here we need to have a single variable, the input X as parameter, since this method will be part of the scikitlearn pipeline.
       And so we use a dataclass instead.
    """
    full_features_df = dfs.base_xy_df.merge(dfs.oil_df, on='date',how='left')
    full_features_df = full_features_df.merge(dfs.stores_df, on=['store_nbr'], how='left')
    full_features_df = full_features_df.merge(dfs.special_days_df, on='date', how='left')
    full_features_df = full_features_df.merge(dfs.transactions_df, on=['date', 'store_nbr'], how='left')
    return full_features_df

def reorder_features_dataset(features_df):
    """Reorder the columns in the feature dataframe so the table becomes easier to understand and inspect. Does not affect the rows."""
    return features_df[[
                'store_nbr', 'store_city', 'store_state', 'store_type', 'store_cluster',
                'days_since_start', 'day_of_week','day_of_month', 'is_15th', 'is_last_day_of_month', 'day_of_year',  
                'day_type', 'special_day_reason', 'special_day_offset', 'special_day_transferred', 'special_day_reason_subtype', 'special_day_locale_type', 'special_day_locale',
                'oil_price', 'all_products_transactions', 
                'product_family', 'products_of_family_on_promotion',
                'sales'
            ]]

def one_hot_encode_necessary_features(features_df, names_of_columns_to_ohe): #TODO make it be done using scklearn one hot encoder?
    """One hot encodes the columns, using their name as prefix, and adding them into the same place the original was, while removing the original """
    #holiday_transferred may be better vectorized. Day type might be too. holiday_locale_type too.
    #This is because their values might have meaning in the order.
    
    #features_df.store_cluster = features_df.store_cluster.astype('int32')
    print(f'Columns in the  features_df of one_hot_encode_necessary features are \n {features_df.columns}')
    
    for name_of_column_to_ohe in names_of_columns_to_ohe:
        index_of_col_to_ohe = features_df.columns.get_loc(name_of_column_to_ohe)
        one_hot_encoded_column:pd.DataFrame = pd.get_dummies(features_df[name_of_column_to_ohe], dummy_na=True, prefix=name_of_column_to_ohe)
        
        # Split the dataframe into two parts: before and after the position of the original column
        columns_before_col_to_ohe = features_df.iloc[:, :index_of_col_to_ohe]
        columns_after_col_to_ohe = features_df.iloc[:, index_of_col_to_ohe+1:] #Exclude the current column

        # Concatenate the two parts with the one-hot encoded dataframe in between
        features_df = pd.concat([columns_before_col_to_ohe, one_hot_encoded_column, columns_after_col_to_ohe], axis=1)

    return features_df

def process_numerical_features(features_df, normalizers, is_test_data): #Should take the normalizer as parameter.
    """Either normalize or standardize variables depending on their distribution. Also handle missing values where necessary. """
    numerical_variable_names = ['oil_price', 'all_products_transactions']

    #Normalization is a scaling technique in which values are shifted and rescaled so that they end up ranging between 0 and 1. It is also known as Min-Max scaling.
    #Its more robust than standarization since it doesnt require the distribution to be gaussian.
    #MinMaxScaler is a scikitlearn normalizer.

    for variable_name in numerical_variable_names: #TODO MAKE IT CHECK IF ITS TEST AND TRANSFORM INSTEAD OF FIT TRANSFORM
        features_df[variable_name + '_standardized'] = normalizers[variable_name].fit_transform(features_df[variable_name])
        #features_df[variable_name + '_normalized'] = normalizers[variable_name].fit_transform(features_df[variable_name]) #hadd double brakcets


    return features_df
    #TODO #return the dataset and the normalizer

def fill_missing_transactions(features_df):
    """Fill transactions missing values with 0. Since it seems they weren't registered when the store didn't exist 
       Let the model know we filled it by adding a feature indicating it.
    """
    features_df['all_transactions_filled'] = features_df.all_products_transactions.isna()
    features_df.all_products_transactions = features_df.all_products_transactions.fillna(0)
    return features_df

def fill_missing_oil_values(features_df):
    # Oil price highly varies over time, making average imputing inaddecuate.
    # While we could use the average between the previous day and the next day, that wouldnt work for forecasting.
    # Instead just use the last known price, sinceFill down
    features_df['oil_price'] = features_df['oil_price'].ffill()#.fillna(method='ffill')
    features_df['oil_price'] = features_df['oil_price'].bfill() #Make sure that if the first elements are blank they still get a price (the price after them).
    #features_df['oil_price'].interpolate(limit_direction="both")
    return features_df


def refine_special_day_reason(features_df):
    """Assign the same reason to special days that have the same reason but with a small variation, storing otherwise lost information in other columns"""

    # Create a special_day_reason subtype column. Extract the subtype of mundial de futbol brasil into a subtype column, since they all have a common reason.
    features_df['special_day_reason_subtype'] = features_df['special_day_reason'].apply(lambda x: x.replace('Mundial de futbol Brasil: ', '').replace('Mundial de futbol Brasil', '') if (type(x) == str) and (x.startswith('Mundial de futbol Brasil')) else '')
    
    # Create a function to extract the offset in any reasons that end with -number or +number
    # Function to process the special_day_offset column
    def get_special_day_offset(value):
        if type(value) == str:
            match = re.search(r'([-+]\d+)$', value)
            if match:
                # Return the number with the sign as an integer
                return int(match.group())

            # If the condition is not met, return NaN
        return 0
    
    #Use the function to create a special_day_offset_column, and convert it from int64 to int32 to save space. 
    features_df['special_day_offset'] = features_df['special_day_reason'].apply(get_special_day_offset).astype('int32')


    # Now that the data that is not stored elsewhere has been stored create a function to clean the special_day_reason column
    def process_special_day_reason_value(value):
        '''A function to process the special_day_reason elements that can be applied element-wise using pandas.'''

        if type(value) == str:
            #If the reason contains a locale, eliminate the locale part of the reason, since its already stored in locale column.
            prefixes = ['Fundacion', 'Independencia', 'Provincializacion', 'Cantonizacion', 'Translado']
            for prefix in prefixes:
                if value.startswith(prefix):
                    value = prefix
            
            # If if value ends with - followed by any number or + followed by any number, aka if it has an offset, eliminate the offset part of the reason, since its already stored in the offset column.  
            match = re.search(r'([-+]\d+)$', value) # Check if value ends with - followed by any number or + followed by any number
            if match:
                return value.replace(match.group(), '') # Return the string without the number and sign
            
            # If the reason is mundial de futbol brasil, eliminate additional detaisl since they are already stored in the reason_subtype column. #Todo verify synthax
            if 'Mundial de futbol Brasil' in value: #value.contains('Mundial de futbol Brasil'):
                return 'Mundial de futbol Brasil'
        
        # If the reason does not need any preprocessing just return it
        return value

    #And now apply that function element-wise to cleanup the special_day_reason column to not store redundant info and unify reasons that are actually the same.
    features_df['special_day_reason'] = features_df['special_day_reason'].apply(process_special_day_reason_value)

    return features_df


def replace_date_with_date_related_columns(features_df):
    """"Adds many date_related_columns """
    #Providing a date_time format speeds the method up.https://www.kaggle.com/code/kuldeepnpatel/to-datetime-is-too-slow-on-large-dataset
    features_df['date'] = pd.to_datetime(features_df['date'],format='%Y-%M-%d')#%Y-%M-%d # = yyyy-mm-dd, ex= 2013-01-21
    #Calculate the absolute date (from unix epoch), which is a standard start date used by many siystems and libraries working with time series data.
    #While this would work its probably worth for the nn to learn.
    #UNIX_EPOCH = pd.Timestamp("1970-01-01")
    #features_df['absolute_day_number'] = (features_df['date'] - UNIX_EPOCH) // pd.Timedelta('1D')

    #Calculate the number of days since the first date in the dataset. Change the type from int64 to in32 since it won't have nulls.
    features_df['days_since_start'] = ( (features_df['date'] - features_df['date'].min()) // pd.Timedelta('1D') ).astype('int32')

    features_df['day_of_year'] = features_df['date'].dt.dayofyear
    features_df['day_of_month'] = features_df['date'].dt.day
    features_df['day_of_week'] = features_df['date'].dt.dayofweek

    features_df['is_15th'] = (features_df['date'].dt.day == 15).astype(int)
    features_df['is_last_day_of_month'] = (features_df['date'] == features_df['date'] + MonthEnd(1)).astype(int)

    #features_df = features_df.drop(columns=['date'])
    return features_df



def prepare_features_df(features_df:pd.DataFrame, stores_df, oil_df, transactions_df, special_days_df, normalizers):
    """Call all the preprocessing methods in order, and prepare a features dataframe for deep learning, be it the train set or the test set"""
    #TODO READ and rename columns of the dataset, and then process them here.
    features_df = merge_data_sources(features_df, stores_df, oil_df, transactions_df, special_days_df) #Careful, do not move this later, since the rest of the methods need access to all the columns.
    features_df = reorder_features_dataset(features_df) #Careful, do not move this later, the rest of the methods try to respect the order of the dataframe, so theyll end up in messy places otherwise.
    features_df = fill_missing_oil_values(features_df)     
    features_df = refine_special_day_reason(features_df)
    features_df = process_numerical_features(features_df) #Rename or include fill missing oil values here?
    features_df = one_hot_encode_necessary_features(features_df) #Careful moving this earlier since one hot encoding properly requires categorical variables to have been processed.
    features_df = replace_date_with_date_related_columns(features_df) #Careful, moving calling this earlier could be problematic since it eliminates date column.

    return features_df

#def window_sales():

def rolling_window_dataset(df:pd.DataFrame, window_size):
    """Window the dataset so that it can be used for training a neural network.
       Creates a rolling window, aka if a series on the dataframe was 1,2,3 and window size was 2 the new series that will be on another column on a dataframe will be [1,2], [2,3]
       It creates 'lag features' which can be used in the prediction of the future values, in addition to the values of the variables.
    """
    #Create shifted versions of the entire dataframe. One shifted version per day in the window after the first one. 
    dataframes = [df]
    for lag in range(1, window_size):
        #Create the shifted dataframe, making sure it keeps the appropiate dtypes
        df_shifted = df.shift(lag)
        df_shifted = df_shifted.iloc[window_size-1:]  # Remove rows that will lack values
        df_shifted = df_shifted.astype(df.dtypes)
        dataframes.append(df_shifted.add_suffix(f'_lag_{lag}'))
    
    # Remove rows that will make rows that lack values on joining with other dfs.
    dataframes[0] = dataframes[0].iloc[window_size-1:]

    #Horizontally concatenate all the shifted dataframes.
    df_concat = pd.concat(dataframes, axis=1)

    return df_concat
    #We could add some lead_time like this:
    #def make_lags(ts, lags, lead_time=1): #https://www.kaggle.com/code/ryanholbrook/forecasting-with-machine-learning
    # return pd.concat(
    #     {
    #         f'y_lag_{i}': ts.shift(i)
    #         for i in range(lead_time, lags + lead_time)
    #     },
    #     axis=1)

def drop_target(df:pd.DataFrame):
    """Drop the target for prediction from the values
       It is convenient/necessary for having windowing inside the pipeline
       But must be droped for the model to be valid.
       This method is used by the pipeline to achieve that.
    """
    return df.drop(columns='sales')


#perform fourier transform?
#Inpute missing values in other columns? 

#TODO train_val_split, probably the most sensible approach for a simple time series analysis is to use the last data for validation,
#though i can imagine other approaches which could lead to better peformance, for example masking like bert does for text data.
#Or creating crossval sets by skipping part of the time before prediction

from sklearn.model_selection import KFold
from sklearn.pipeline import FunctionTransformer
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression

def create_pipeline(window_size=3, verbose=False):
    """Create a pipeline for data processing
       Keep in mind that pipelines are extremely practical, and easy to debug.
       You can call parts of the pipeline for debugging purposes by adding a list slicer next to it, for example pipeline[:1].fit_transform(dataset) or by name of the step.
       You can also call the pipeline with 'verbose=True' to analyze the time taken by each step.
       You can use ipython.display to display a graph of the pipeline steps too. Though it seems functiontransformer isnt really named with this way of defining them, you can create a class extending function transformer instead.
    """
    cat_cols_to_ohe = [ 'store_nbr', 'store_cluster', 'product_family', 'store_city','store_state', 'store_type', 'day_type', 'special_day_locale_type', 'special_day_locale', 'special_day_reason', 'special_day_reason_subtype',  'special_day_transferred']
    numerical_features_to_min_max_scale = ['oil_price', 'all_products_transactions']

    pipeline = Pipeline([
        ('rename_columns', FunctionTransformer(rename_raw_dfs_cols)),
        ('merge_dataframes', FunctionTransformer(merge_data_sources)), #, kw_args={'stores_df': stores_df, 'oil_df': oil_df, 'transactions_df': transactions_df, 'special_days_df': special_days_df}
        ('fill_missing_oil_values', FunctionTransformer(fill_missing_oil_values)), #Could be achievable with sklearn most likely
        ('fill_missing_transactions', FunctionTransformer(fill_missing_transactions)),
        ('refine_special_day_reason', FunctionTransformer(refine_special_day_reason)), #Isnt placed where the column came from.
        ('replace_date_with_date_related_columns', FunctionTransformer(replace_date_with_date_related_columns)), #Careful, moving calling this earlier could be problematic since it eliminates date column.
        ('reorder_features', FunctionTransformer(reorder_features_dataset)),
        ('prepare_features', ColumnTransformer([
            ('standardize_numerical_features', MinMaxScaler(), numerical_features_to_min_max_scale), 
            #Could probably be transformed to one hot encoding directly, and param can probably be removed since all the columns which get the transforme will need it to be but who knows.
            ('prepare_categorical_columns', FunctionTransformer(one_hot_encode_necessary_features, kw_args={'names_of_columns_to_ohe': cat_cols_to_ohe}), cat_cols_to_ohe)
        ], remainder='passthrough', sparse_threshold=0, n_jobs=3, verbose_feature_names_out=False).set_output(transform='pandas')),
        ('window_dataset', FunctionTransformer(rolling_window_dataset, kw_args={'window_size': window_size})),
        ('drop_target', FunctionTransformer(drop_target)),
        #,
        ('model', LinearRegression())
    ], verbose=verbose)
    return pipeline
    #TODO batch the pipeline if possible.