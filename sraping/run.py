import pandas as pd
import numpy as np
import time
import datetime
import random
import os
from collections import Counter
import sys, traceback
# from logging import Logger
import logging
logger = logging.Logger('catch_all')

from bs4 import BeautifulSoup
import requests

import selenium
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

#Chrome
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc
# import undetected_chromedriver.v2 as uc

#Firefox
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
# from selenium.webdriver.firefox.options import Log
from webdriver_manager.firefox import GeckoDriverManager

import warnings
warnings.filterwarnings("ignore")

def randomProxy():
    df_proxy_list = pd.read_excel('proxy_list.xlsx')
    proxy_list = df_proxy_list.iloc[:,0].values
    random_proxy = random.choice(proxy_list)
    # random_proxy = "http://"+ random.choice(proxy_list)
    # random_proxy = random.choice(proxy_list).split(":")[0]
    # random_proxy = "50.228.141.100:80"
    # print("Proxy Server:", random_proxy)
    return random_proxy

def randomUserAgent():
    df_ua_list = pd.read_excel('user_agent_list.xlsx')
    user_agent_list = df_ua_list.iloc[:,0].values
    random_user_agent = random.choice(user_agent_list)
    # print("User Agent:", random_user_agent)
    headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.8",
    "upgrade-insecure-requests": "1", 
    "Connection": "keep-alive",
    "Host": "zf2-client.local",
    "x-insight": "activate",
    "user-agent": random_user_agent
    }
    return headers

def webdriverFirefox():
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.firefox.options import Options
    service = webdriver.FirefoxService(GeckoDriverManager().install())
    option = webdriver.FirefoxOptions()
    # option.add_experimental_option("excludeSwitches", ["enable-logging"])
    # option.add_argument(" — window-size=1920,1200")
    option.add_argument('--disable-gpu')
    option.add_argument("--disable-extensions")
    option.add_argument("--disable-application-cache")
    option.add_argument("--disable-session-crashed-bubble")
    option.add_argument("--no-sandbox")
    option.add_argument("--disable-dev-shm-usage")
    option.add_argument("--start-maximized")
    option.add_argument("--disable-infobars")
    option.add_argument("--disable-notifications")
    option.add_argument("--disable-popup-blocking")
    option.add_argument("--headless=new")
    option.headless = True
    option.add_argument(f"proxy-server={randomProxy()}, user-agent={randomUserAgent()}")
    # Initialize the webdriver
    driver = webdriver.Firefox(service=service, options=option)   
    return driver

def sleeping(RetryTime):
    for i in range(RetryTime+1):
        print(f"{i}", end="\r", flush=True)
        time.sleep(1)

def navigateAndPull(url):
    driver = webdriverFirefox()
    driver.get(url)
    # print(driver.title)
    driver.maximize_window()
    time.sleep(3)
 
    # ZILLOW ERROR PAGE
    errorr = None
    try:
        driver.find_element(by=By.XPATH, value="//div[@id='zillow-error-page']")
        print("The error_page EXISTS.")
        errorr = True
        # driver.quit()
        # page_statement == "true"
        # result_count == -1        
    except Exception as ex:
        print("The error_page DOES NOT EXISTS.")
        # print(str(ex)) 
        pass

    # CATHCHA ERROR PAGE
    try:
        driver.find_element(by=By.XPATH, value="//div[@id='px-captcha-wrapper']")
        print("The captcha_page EXISTS.")
        errorr = True
        # error = True
        # driver.quit()
        # page_statement == "true"
        # result_count == -1    
    except Exception as ex:
        print("The captcha_page DOES NOT EXISTS.")
        # print(str(ex))        
        pass  
    
    y = 0 
    while True:
        try:
            aa = driver.find_element(by=By.XPATH, value="//div[@id='search-page-list-container']")
            # driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            driver.execute_script("arguments[0].scrollBy(0,600);", aa)
            # driver.execute_script("arguments[0].scrollTo(0,6000);", aa)  
        except Exception as ex:
            print("aa Exception Error:", ex)
            print(str(ex))
            break
        y += 1
        time.sleep(0.05)
        if y > 9:
            break

    # PULLING THE DATA
    linklist=[]
    pricelist=[]
    featurelist=[]
    addresslist=[]
    agentlist=[]
    county=[]
    df_linklist = pd.DataFrame() 
    try:
        # links = driver.find_elements(by=By.XPATH, value="//div[@id='grid-search-results']/ul/li//a[@data-test='property-card-link']")
        links = driver.find_elements(by=By.XPATH, value="//div[@id='grid-search-results']/ul/li//div[@class='StyledPropertyCardDataWrapper-c11n-8-84-3__sc-1omp4c3-0 bKpguY property-card-data']/a")
        # links = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//div[@id='grid-search-results']/ul/li//a[@data-test='property-card-link']")))
        # links = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//div[@id='grid-search-results']/ul/li//div[@class='StyledPropertyCardDataWrapper-c11n-8-84-3__sc-1omp4c3-0 bKpguY property-card-data']/a")))
        linklist = [link.get_attribute("href") for link in links]
        print(f"linklist: {len(linklist)}")
        # prices = driver.find_elements(by=By.XPATH, value="//ul[@class='List-c11n-8-84-3__sc-1smrmqp-0 StyledSearchListWrapper-srp__sc-1ieen0c-0 doa-doM fgiidE photo-cards photo-cards_extra-attribution']//span[@data-test='property-card-price']")
        prices = driver.find_elements(by=By.XPATH, value="//div[@id='grid-search-results']/ul/li//span[@data-test='property-card-price']")
        pricelist = [price.text for price in prices]
        print(f"pricelist: {len(pricelist)}")
        # features = driver.find_elements(by=By.XPATH, value="//ul[@class='StyledPropertyCardHomeDetailsList-c11n-8-84-3__sc-1xvdaej-0 eYPFID']")
        # featurelist = [feature.text for feature in features]
        # features = driver.find_elements(by=By.XPATH, value="//div[@class='StyledPropertyCardDataArea-c11n-8-84-3__sc-yipmu-0 dbDWjx']")
        features = driver.find_elements(by=By.XPATH, value="//div[@id='grid-search-results']/ul/li/div//div[@class='StyledPropertyCardDataArea-c11n-8-84-3__sc-yipmu-0 dbDWjx']")
        featurelist = [feature.text for feature in features]
        print(f"featurelist: {len(featurelist)}")
        # addresses = driver.find_elements(by=By.XPATH, value="//address[@data-test='property-card-addr']")
        addresses = driver.find_elements(by=By.XPATH, value="//div[@id='grid-search-results']/ul/li/div//address")
        addresslist = [address.text for address in addresses]
        print(f"addresslist: {len(addresslist)}")
        # agents = driver.find_elements(by=By.XPATH, value="//div[@class='StyledPropertyCardDataArea-c11n-8-84-3__sc-yipmu-0 jretvB']")
        agents = driver.find_elements(by=By.XPATH, value="//div[@id='grid-search-results']/ul/li//div[@class='StyledPropertyCardDataArea-c11n-8-84-3__sc-yipmu-0 jretvB']")
        agentlist = [agent.text for agent in agents] 
        print(f"agentlist: {len(agentlist)}")
        try:
            # county = driver.find_elements(by=By.XPATH, value="//ul[@class='sc-eeMvmM bApXoY']")[0].text.split()[-3]
            county = driver.find_elements(by=By.XPATH, value=" //div[@id='region-info-footer']/ul/li[3]")[0].text.split()[0]
            print("county: ", county)
        except Exception as ex:
            county="nolink"
            print("county No link found", str(ex))
        results=[]
        for i in range(len(linklist)):
            result_dict = {
                            'prices': pricelist[i],
                            'features': featurelist[i],
                            'addresses': addresslist[i],
                            'agents': agentlist[i],
                            'counties': county,
                            'links': linklist[i]
                        }
            results.append(result_dict)
        df_linklist = pd.DataFrame(results)
        # print("df_linklist   :", df_linklist)
    except Exception as ex:
        print("navigateAndPull - No link found")
        print("str(ex  :)", str(ex))
        # print(str(ex))
        pass
       
    # CHECKING PAGE STATEMENT
    try:
        page_statement = driver.find_element(by=By.XPATH, value="//a[@title='Next page']").get_attribute('aria-disabled')
    except:
        print("navigateAndPull - page_statement Not Found Error")
        page_statement = "true"
        pass

    # CHECKING RESULT COUNT
    try:
        result_count = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//span[@class='result-count']"))).text.split()[0]
        result_count2 = driver.find_elements(by=By.XPATH, value="//span[@class='result-count']")[0].text.split()[0]
        # result_count3 = driver.find_elements(by=By.XPATH, value="//span[@class='result-count']")
        # result_count4 = driver.execute_script("arguments[0].value", result_count3[0].text.split()[0])

        print(f"result_count: {int(result_count)}")
        # print(f"result_count2: {int(result_count2)}")
        # print(f"result_count4: {int(result_count4)}")
    except Exception as ex:
        print("No result_count found")
        print("str(ex  :)", str(ex))
        result_count = -1
        pass
    
    driver.quit()
    return df_linklist, page_statement, int(result_count), errorr


def finalPulling(State_Zipcode, Type, RetryTime):
    df = pd.DataFrame() 
    pageNo = 1
    result_countt_list=[]
    while True:             
        url = (f"https://www.zillow.com/{State_Zipcode}/{Type}/{pageNo}_p/")
        df_linklist, page_statementt, result_countt, errorr = navigateAndPull(url)
        result_countt_list.append(result_countt)
        most_common_result_countt = Counter(result_countt_list).most_common(1)[0][0]
        print(Counter(result_countt_list))
        print("most_common_result_countt: ", most_common_result_countt)
        # print("df_linklist   ++++:", df_linklist)
        df_linklist.insert(0, "zipcodes", State_Zipcode)
        print(f"{State_Zipcode} -- Page-{pageNo} is pulled: {len(df_linklist)}")
        print("++++++++++++++++++++++++++++++")       
        df = pd.concat([df, df_linklist], axis = 0)
        # print("page out df", df)
        # print("page out df_linklist", df_linklist)
        if page_statementt == "true":
            print("page_statementt is true")
            # sleeping(RetryTime)
            # print("page in df", df)
            if errorr == True:
                print("errorr page is true")
                # sleeping(420)
                pageNo -=1
            else:         
                break
        if int(np.ceil(most_common_result_countt/41)) == pageNo:
            print("result_count==pageNo")
            break 
        pageNo += 1
        print("sleeping finalPulling")
        sleeping(RetryTime)
    return df.reset_index(), pageNo

def run(StateIndexNo, TypeIndexNo, RetryTime, zipCodeRank):
    df_state = pd.read_csv("df_state.csv")   
    # StateIndexNo = 3
    # StateIndexNo = int(input("Input the State Index:"))
    ZipCodeList = df_state["Unique_Zipcode"][StateIndexNo].split()
    # ZipCodeList = "ri-02903 ri-02902 ri-02818".split()
    # TypeIndexNo = 0
    # RetryTime = 20
    TypeList = ["","homes","townhomes","duplex","land","condos","mobile"]
    Type = TypeList[TypeIndexNo]
    df = pd.DataFrame()
    count = 1
    dls = 0
    TotalPageNo = 0
    for ZipCode in ZipCodeList[zipCodeRank[0]:zipCodeRank[1]]:  
        try:
            print("///////////////////////////////////////////////////////////////")
            print(f"{len(ZipCodeList)}/{count} State_ZipCode: {ZipCode}")
            # print("State_ZipCode:", ZipCode)
            df_st, PageNo = finalPulling(ZipCode, Type, RetryTime)  
            print("Number of links:", df_st.shape[0])
            print("duplicated links sum:", df_st.duplicated().sum())
            print("------------------------------")
            df = pd.concat([df, df_st], axis = 0)
            try:
                dls += df_st.links.duplicated().sum()
            except Exception as ex:
                print("Links error: ", str(ex))
                pass
            TotalPageNo += PageNo
            if len(ZipCodeList) > 1 and len(ZipCodeList) == count:
                break
            # else:
            #     sleeping(RetryTime)
            count += 1
            print("sleeping - run - try")
            sleeping(RetryTime)
        # except Exception as ex: 
        # except ValueError as ex:
        except Exception as ex:
            count += 1     
            bugun = datetime.datetime.strftime(datetime.datetime.today(), '%d.%m.%Y')
            path = "./link_lists/"
            # fileName = "file_"+(df_state['State_Name'][StateIndexNo])+"_"+Type+"_"+bugun+".csv"
            fileName = "file_"+(df_state['State_Name'][StateIndexNo])+"_"+Type+"_("+str(zipCodeRank[0])+"-"+str(zipCodeRank[1])+")_"+bugun+".csv"
            df.to_csv(os.path.join(path, fileName))
            print("sleeping - run - except") 
            print("str(ex  :)", str(ex))          
            sleeping(RetryTime)
            pass

    bugun = datetime.datetime.strftime(datetime.datetime.today(), '%d.%m.%Y')
    path = "./link_lists/"
    # fileName = "file_"+(df_state['State_Name'][StateIndexNo])+"_"+Type+"_"+bugun+".csv"
    fileName = "file_"+(df_state['State_Name'][StateIndexNo])+"_"+Type+"_("+str(zipCodeRank[0])+"-"+str(zipCodeRank[1])+")_"+bugun+".csv"
    df.to_csv(os.path.join(path, fileName))
    print("***************************")
    print("Number of links(df):", df.shape[0])
    print("duplicated links sum(df):", df["links"].duplicated().sum())
    print("duplicated links sum(df_st):", dls)
    print("TotalPageNo(df):", TotalPageNo)


run(StateIndexNo=61, TypeIndexNo=0, RetryTime=300, zipCodeRank=[7,10])