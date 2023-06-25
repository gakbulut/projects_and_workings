import streamlit as st
import pandas as pd
import numpy as np
import sklearn
import pickle
import joblib
import xgboost

st.set_page_config(page_title="House Price Prediction in Turkey",
                   page_icon="house", layout="wide")

# st.header("ARTIFICIAL INTELLIGENCE SUPPORTED HOUSING SALES PRICE PREDICTION IN TURKEY (İSTANBUL - ANKARA - İZMİR))")
st.markdown("<h1 style='text-align: center; font-size: 32px; color: #2196F3;'>ARTIFICIAL INTELLIGENCE SUPPORTED HOUSING SALES PRICE PREDICTION IN TURKEY (İSTANBUL - ANKARA - İZMİR) </h1>", unsafe_allow_html=True)
st.markdown("<h1 style='text-align: center; font-size: 30px; color: #008000;'> TÜRKİYEDE (İSTANBUL - ANKARA - İZMİR) <br/> YAPAY ZEKA DESTEKLİ KONUT SATIŞ FİYATI TAHMİNİ  </h1>", unsafe_allow_html=True)
st.markdown("<h1 style='text-align: center; font-size: 20px; color: #2196F3;'>You can make a housing sales price estimation by entering the necessary information given on the below.</h1>", unsafe_allow_html=True)
st.markdown("##")

# st.header("HOUSE PRICE PREDICTION IN TURKEY (İSTANBUL - ANKARA - İZMİR)")
st.markdown("<h1 style='text-align: left; font-size: 24px; color: #2196F3;'>Please select the features of the house.</h1>", unsafe_allow_html=True)
st.markdown("<h1 style='text-align: left; font-size: 22px; color: #008000;'> All values must be entered </h1>", unsafe_allow_html=True)

# st.title("Please select the features of the house.")

# streamlit sharing
xx = pd.read_csv(
    "/app/projects_and_workings/Real_life_projects/House_Price_Prediction/deployment/streamlit_sharing/df_new_grouped.csv")

df_new_grouped = pd.DataFrame(xx)
# df_new_grouped.set_index("date", inplace=True)


province = st.selectbox("What province is your house in?",
                        df_new_grouped.province.sort_values().unique())

# county = st.selectbox("What county is your house in?", df_new_grouped.county.sort_values().unique())
for i in df_new_grouped.province.sort_values().unique():
    k = df_new_grouped[df_new_grouped.province ==
                       i].county.sort_values().unique()
    if province == i:
        county = st.selectbox("What county is your house in?", k)

# neighborhood = st.selectbox("What neighborhood is your house in?", df_new_grouped.neighborhood.sort_values().unique())
for i in df_new_grouped.county.sort_values().unique():
    k = df_new_grouped[df_new_grouped.county ==
                       i].neighborhood.sort_values().unique()
    if county == i:
        neighborhood = st.selectbox("What neighborhood is your house in?", k)

# room_hall = ["1 + 0", "1 + 1", "2 + 0", "2 + 1", "2 + 2", "3 + 0", "3 + 1", "3 + 2", "4 + 0", "4 + 1",
#              "4 + 2", "5 + 0", "5 + 1", "5 + 2", "6 + 0","6 + 1", "6 + 2"]
# norh = st.selectbox("Which 'Number of Rooms + Living Room' style is your house in?", room_hall)
for i in df_new_grouped.neighborhood.sort_values().unique():
    k = df_new_grouped[df_new_grouped.neighborhood ==
                       i]["Room + Hall Number"].sort_values().unique()
    if neighborhood == i:
        norh = st.selectbox(
            "Which 'Number of Rooms + Living Room' style is your house in?", k)

floors = ["Bodrum (Basement)", "Yarı Bodrum (Semibasement)", "Zemin (Ground)", "Çatı Katı (Loft)", "1", "2", "3", "4", "5", "6-10", "11-15",
          "16-20", "21 and over"]
Floor = st.selectbox("What floor is your house on?", floors)
# for i in df_new_grouped.neighborhood.sort_values().unique():
#     k = df_new_grouped[df_new_grouped.neighborhood == i]["Floor"].sort_values().unique()
#     if neighborhood == i:
#         Floor = st.selectbox("What floor is your house on?", k)

nofloors = ["1", "2", "3", "4", "5", "6-10", "11-15", "16-20", "21 and over"]
nof = st.selectbox(
    "How many floors is your house located in the building?", nofloors)
# for i in df_new_grouped.neighborhood.sort_values().unique():
#     k = df_new_grouped[df_new_grouped.neighborhood == i]["Number of Floors"].sort_values().unique()
#     if neighborhood == i:
#         nof = st.selectbox("How many floors is your house located in the building?", k)

nobs = [1, 2, 3, 4, 5, 6]  # ["1", "2", "3", "4", "5", "6"]
nob = st.selectbox("How many bathrooms in your house?", nobs)
# for i in df_new_grouped.neighborhood.sort_values().unique():
#     k = df_new_grouped[df_new_grouped.neighborhood == i]["Number of Bathrooms"].sort_values().unique()
#     if neighborhood == i:
#         nob = st.selectbox("How many bathrooms in your house?", k)

sides = [1, 2, 3, 4]
facade = st.selectbox("How many sides does your house have?", sides)
# for i in df_new_grouped.neighborhood.sort_values().unique():
#     k = df_new_grouped[df_new_grouped.neighborhood == i]["Facade_count"].sort_values().unique()
#     if neighborhood == i:
#         facade = st.selectbox("How many sides does your house have?", k)

heating = ["Kombi (Combi boiler)", "Merkezi (Central)", "Klima (Air conditioning)",
           "Soba (Stone)", "Kat Kaloriferi (Floor Heater)", "Diğer (Other)"]
heating_type = st.selectbox("What is your house heating type?", heating)
# for i in df_new_grouped.neighborhood.sort_values().unique():
#     k = df_new_grouped[df_new_grouped.neighborhood == i]["Heating Type"].sort_values().unique()
#     if neighborhood == i:
#         heating_type = st.selectbox("What is your house heating type?", k)


insite = st.selectbox("Is your house in the site?", ["Yes", "No"])
# for i in df_new_grouped.neighborhood.sort_values().unique():
#     k = df_new_grouped[df_new_grouped.neighborhood == i]["On Site"].sort_values().unique()
#     if neighborhood == i:
#         insite = st.selectbox("Is your house in the site?", k)

Net_M2 = st.number_input("What is the net m2 area of your house?")
age = st.slider("What is the age of your house?", 0, 50)
# age = st.text_input("What is the age of your house?")
dolar = st.number_input(
    "What is the current dollar rate? Please use point (.) for decimal number")


my_dict = {
    "province": province,
    "county": county,
    "neighborhood": neighborhood,
    "Room + Hall Number": norh,
    "Net_M2": int(Net_M2),
    "Floor": Floor,
    "Number of Floors": nof,
    "Building Age": age,
    "Number of Bathrooms": nob,
    "Facade_count": facade,
    "Heating Type": heating_type,
    "Inside the Site": insite,
    "dolar": dolar
}

df = pd.DataFrame.from_dict([my_dict])
st.markdown("<h1 style='text-align: left; font-size: 28px; color: #2196F3;'>Your House Features</h1>",
            unsafe_allow_html=True)

st.table(df)
st.markdown("---")
st.markdown("<h1 style='text-align: left; font-size: 20px; color:#2196F3;'>Click on the button below to find out the sales price estimation of your house based on the information entered:</h1>", unsafe_allow_html=True)

# streamlit sharing
X_new = pd.DataFrame(pd.read_csv(
    "/app/projects_and_workings/Real_life_projects/House_Price_Prediction/deployment/streamlit_sharing/X_new_single_row.csv"))
X_new.set_index("date", inplace=True)

df = pd.get_dummies(df).reindex(columns=X_new.columns, fill_value=0)

# streamlit sharing
model = pickle.load(open(
    "/app/projects_and_workings/Real_life_projects/House_Price_Prediction/deployment/streamlit_sharing/best_model_xgbm_final.pkl", "rb"))

# streamlit sharing
scaler = joblib.load(
    "/app/projects_and_workings/Real_life_projects/House_Price_Prediction/deployment/streamlit_sharing/scaler")

# df = scaler.transform(df)

prediction = model.predict(df)
# st.info(prediction)

if st.button("Prediction"):
    st.info("The estimated price of your house is {price:,} ₺. &nbsp; &nbsp; &nbsp; &nbsp; TRAIN R2: 0.95, TEST R2: 0.90".format(
        price=int(prediction[0])*int(Net_M2)))
    # st.markdown("<p style='text-align: center; font-size: 18px; color:#4D4D4D'><b>Güneş Akbulut</b> <br/> Data Scientist &nbsp; & &nbsp;<p/>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 18px; color:#4D4D4D'><b>Güneş Akbulut</b> <br/> Data Scientist <br /> <a href = https://www.linkedin.com/in/gunesakbulut> Linkedin <a/><p/>", unsafe_allow_html=True)
