import numpy as np
from flask import Flask, request, render_template
import pickle
import joblib
import pandas as pd

app = Flask(__name__)


@app.route("/")
def home():
    return(render_template("index.html"))


# @app.route("/predict", methods=["post", "get"])
@app.route("/predict", methods=["post"])
def predict():
    province_ = str(request.form.get("province-select").capitalize())
    county_ = str(request.form.get("county-select").capitalize())
    neighborhood_ = str(request.form.get("neighborhood-select").capitalize())
    norh_ = str(request.form.get("norh-select"))
    Net_M2_ = request.form.get("Net_M2-select")
    floor_ = str(request.form.get("floor-select"))
    nof_ = str(request.form.get("nof-select"))
    age_ = request.form.get("age-select")
    nob_ = str(request.form.get("nob-select"))
    facade_ = request.form.get("facade-select")
    heating_type_ = str(request.form.get("heating_type-select"))
    insite_ = request.form.get("insite-select")
    dolar_ = request.form.get("dolar-select")
    my_dict = {
        "province": province_,
        "county": county_,
        "neighborhood": neighborhood_,
        "Room + Hall Number": norh_,
        "Net_M2": Net_M2_,
        "Floor": floor_,
        "Number of Floors": nof_,
        "Building Age": age_,
        "Number of Bathrooms": nob_,
        "Facade_count": facade_,
        "Heating Type": heating_type_,
        "Inside the Site": insite_,
        "dolar": dolar_
    }

    df = pd.DataFrame.from_dict([my_dict])

    # local
    X_new = pd.DataFrame(pd.read_csv("X_new_single_row.csv"))
    X_new.set_index("date", inplace=True)

    df = pd.get_dummies(df).reindex(columns=X_new.columns, fill_value=0)

    model = pickle.load(open("best_model_xgbm_final.pkl", "rb"))

    # scaler = joblib.load("scaler")
    # df = scaler.transform(df)

    prediction = model.predict(df)
    print(province_)
    print(county_)
    print(neighborhood_)
    print(norh_)

    print(prediction[0])
    print(Net_M2_)
    output = round((prediction[0]*int(Net_M2_)))
    print(output)
    return render_template('index.html', prediction_text='The estimated price of your house is {output:,} ₺.  ------ TRAIN R2: 0.95 & TEST R2: 0.90'.format(output=round((prediction[0]*int(Net_M2_)))))


if __name__ == "__main__":
    app.run(debug=True)
