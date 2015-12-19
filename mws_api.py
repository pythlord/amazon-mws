import urllib
import hashlib
import hmac
import base64
from time import strftime, gmtime
import time
import requests
#we need to import socket even though requests already uses it
#see this note about the requests/socket issue: https://github.com/kennethreitz/requests/issues/1236
import socket
import logging
import traceback

#below are MWS access/secret keys
#these are different from the AWS cloud services keys
access_key = '' # length-20 alpha-numberic all-caps string
secret_key = '' # length-40 alpha-numeric upper & lower case string
seller_id = '' # typically a length-14 alpha-numeric all-caps string
marketplace_id = 'ATVPDKIKX0DER' # this is just the US Marketplace ID. it's not a secret string
# the marketplace_id will need to be replaced with a different code for those interacting with non-US marketplaces
user_agent = {'User-Agent': 'python 2.7'}
feedtype = '_POST_PRODUCT_PRICING_DATA_'
# there are many different feedtypes, but the above is most commonly used
# please see http://docs.developer.amazonservices.com/en_DE/feeds/Feeds_FeedType.html
# this document lists all the feedtypes available

#MWSCredentials is just for passing around credentials information in a tidy way
class MWSCredentials(object):
    def __init__(self, access_key, secret_key, seller_id, marketplace_id, user_agent):
        self.access_key = access_key
        self.secret_key = secret_key
        self.seller_id = seller_id
        self.marketplace_id = marketplace_id
        self.user_agent = user_agent

creds = MWSCredentials(access_key, secret_key, seller_id, marketplace_id, user_agent)

def get_timestamp():
    return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())

def calc_md5(str):
    md = hashlib.md5()
    md.update(str)
    return base64.encodestring(md.digest()).strip('\n')

def build_sig_str(access_key, secret_key, seller_id, marketplace_id, extra_sig_params=None):
    sig_params = {  'AWSAccessKeyId' : access_key,
                    'SellerId' : seller_id, #try 'Merchant' or 'SellerId'
                    'SignatureVersion': '2',
                    'Timestamp': get_timestamp(),
                    'Version': '2009-01-01',
                    'SignatureMethod': 'HmacSHA256',
                    'MarketplaceId' : marketplace_id } #try 'MarketplaceId' or 'MarketplaceIdList.Id.1'
    sig_params.update(extra_sig_params or {})
    sig_params_str = '&'.join(['%s=%s' % (k, urllib.quote(sig_params[k], safe='-_.~').encode('utf-8')) for k in sorted(sig_params)])
    return sig_params_str

def get_url_with_sig(sig_header, sig_params_str, secret_key, postfix='/?'):
    sig_str = sig_header + sig_params_str
    newhmac = hmac.new(secret_key, sig_str.encode("utf-8"), hashlib.sha256)
    hashed_sig_str = urllib.quote(base64.b64encode(newhmac.digest()))
    url_header = "https://mws.amazonservices.com" + postfix
    url_contents = sig_params_str + "&Signature=" + hashed_sig_str
    url = url_header + url_contents
    return url

def post_request(url, headers, data=None):
    count = 0
    while True:
        if count == 40:
            break
        try:
            #raise requests.exceptions.ConnectionError("Don't panic, this is just a simulated error!")
            r = requests.post(url, headers=headers, timeout=3.0)
            if not r.status_code == 200:
                r.raise_for_status()
            break
        except requests.exceptions.HTTPError as e:
            count = count + 1
            logging.error(e.message)
            if r.status_code == 503:
                time.sleep(0.5) # wait longer for retrying after 503 response
                print "retrying after 503 (service not ready) response"
            else:
                time.sleep(0.5)
                print "retrying after " + str(r.status_code) + " response"
            continue # go back to the top of the while loop
        except requests.exceptions.ConnectionError as e:
            count = count + 1
            logging.error(e.message)
            print "retrying after ConnectionError"
            continue # go back to the top of the while loop
    return r

def post_request2(url, headers, data=None, max_retries=100):
    count=0
    while count < max_retries:
        count += 1
        #print count
        if count == max_retries:
            print 'request failed (too many retries)'
            raise requests.exceptions.RequestException("Too Many Retries")
        try:
            r = requests.post(url, headers=headers, timeout=2.0)
            #change timeout to 5 or 10 seconds usually
            r.raise_for_status()
            return r
        except requests.exceptions.ConnectTimeout:
            print "ConnectTimeout"
            trace = traceback.format_exc()
            logging.warning('Connection Timeout: {0}'.format(trace))
        except requests.exceptions.ReadTimeout:
            print "ReadTimeout"
            trace = traceback.format_exc()
            logging.warning('Read Timeout: {0}'.format(trace))
        except requests.exceptions.ConnectionError:
            print "ConnectionError"
            trace = traceback.format_exc()
            logging.warning('Connection Error: {0}'.format(trace))
        except (requests.exceptions.Timeout, socket.timeout, socket.error):
            print "SocketTimeout"
            trace = traceback.format_exc()
            logging.warning('Socket Timeout: {0}'.format(trace))
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 503:
                #503 happens when you submit a price feed (or any feed) to much and overflow the bucket
                print "Retrying After 503 (Service Not Ready)"
                time.sleep(20.0)
            elif e.reponse.status_code == 404:
                #404 happens when you query a FeedSubmissionId before feed is finished
                print "Retrying After 404 (FeedSubmissionId Not Ready)"
                time.sleep(20.0)
            else:
                print "HTTPError (Not 503)"
                trace = traceback.format_exc()
                logging.warning('HTTP Error other than 503: {0}'.format(trace))
            #time.sleep(0.5)
        except requests.exceptions.RequestException as e:
            print "GeneralRequestsError"
            trace = traceback.format_exc()
            logging.warning('Requests Error (Other): {0}'.format(trace))
            #time.sleep(0.5)
    return r

def post_request3(url, headers, data=None, max_retries=40):
    count = 0
    while count < max_retries:
        count += 1
        try:
            r = requests.post(url, headers=headers, timeout=3.0)
            if r.status_code == 503:
                print 'received 503; retrying'
                time.sleep(0.5)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException:
            print 'other/unexpected error'
            logging.exception('request failed')
            time.sleep(0.5)

# xmlfeed(x,x) is a helper function for use with feeds_submit_feed(x,x,x,x)
def xmlfeed(sku_price, seller_id):
    # sku_price needs to be a dictionary of SKUs and prices
    # example) sku_price = {'XX-XXXX-XXXX':'9.59', 'XX-XXXX-XXXX':'15.99'}
    m = ['\n<Message><MessageID>{0}</MessageID><Price><SKU>{1}</SKU><StandardPrice currency="USD">{2}</StandardPrice></Price></Message>'.format(i+1,k,v) for i,(k,v) in enumerate(sku_price.iteritems())]
    xml1 = """<?xml version="1.0" encoding="utf-8"?>
<AmazonEnvelope xsi:noNamespaceSchemaLocation="amznenvelope. xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<Header>
<DocumentVersion>1.01</DocumentVersion>
<MerchantIdentifier>"""
    xml2 = """</MerchantIdentifier>
</Header>
<MessageType>Price</MessageType>"""
    xml3 = '\n</AmazonEnvelope>'
    return xml1 + seller_id + xml2 + ''.join(m) + xml3

# BEGIN FEEDS API
def feeds_submit_feed(c, feedtype, content_type, sku_price):
    extra_sig_params = {'Action' : 'SubmitFeed',
                        'FeedType' : feedtype,
                        'PurgeAndReplace' : 'false' }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key)
    #a feed can be an XML or tab-delimited file
    #content_type can be 'text/tab-separated-values; charset=iso-8859-1' or 'text/xml' for NorthAmerica/Europe
    #content_type can be 'text/tab-separated-values; charset=Shift_JIS' or 'text/xml' for Japan
    #content_type can be 'text/tab-separated-values;charset=UTF-8', 'text/tab-separated-values;charset=UTF-16', or 'text/xml' for China
    feed = xmlfeed(sku_price, c.seller_id)
    md = calc_md5(feed)
    headers = c.user_agent
    extra_headers = {'Content-MD5': md, 'Content-Type': content_type}
    headers.update(extra_headers)
    #r = requests.post(url, data=feed, headers=headers)
    #return r.text
    r = post_request2(url, headers=c.user_agent, data=feed, max_retries=100)
    return r

def feeds_cancel_feed_submissions(c):
    extra_sig_params = {'Action' : 'CancelFeedSubmissions'}
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key)
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def feeds_get_feed_submission_list(c):
    extra_sig_params = {'Action' : 'GetFeedSubmissionList'}
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key)
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def feeds_get_feed_submission_list_by_next_token(c, token_str):
    extra_sig_params = {'Action' : 'GetFeedSubmissionListByNextToken',
                        'NextToken' : token_str }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key)
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def feeds_get_feed_submission_count(c):
    extra_sig_params = {'Action' : 'GetFeedSubmissionCount'}
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key)
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def feeds_get_feed_submission_result(c, feed_submission_id):
    extra_sig_params = {'Action' : 'GetFeedSubmissionResult',
                        'FeedSubmissionId' : feed_submission_id }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key)
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

# BEGIN REPORTS API
# need to complete Reports API later
def reports_get_report(c, report_id):
    extra_sig_params = {'Action' : 'GetReport',
                        'ReportId' : report_id }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/\n"
    return None

def reports_get_report_count(c, report_type_list):
    extra_sig_params = {'Action' : 'GetReportCount' }
    return None

def reports_get_report_list(c, max_count, report_type_list):
    extra_sig_params = {'Action' : 'GetReportList' }
    return None

def reports_get_report_list_by_next_token(c, next_token):
    extra_sig_params = {'Action' : 'GetReportListByNextToken' }
    return None

def reports_get_report_request_count(c, date_list):
    extra_sig_params = {'Action' : 'GetReportRequestCount' }
    return None

def reports_get_report_request_list(c, max_count, date_list):
    extra_sig_params = {'Action' : 'GetReportRequestList' }
    return None

def reports_get_report_request_list_by_next_token(c, next_token):
    extra_sig_params = {'Action' : 'GetReportRequestListByNextToken',
                        'NextToken' : next_token }
    return None

def reports_cancel_report_requests(c, request_id):
    extra_sig_params = {'Action' : 'CancelReportRequests',
                        'ReportRequestIdList.Id.1' : request_id }
    return None

def reports_request_report(c, report_type):
    extra_sig_params = {'Action' : 'RequestReport',
                        'ReportType' : report_type }
    return None

# BEGIN FULFILLMENT API
# need to add code for Fulfillment API later

# BEGIN ORDERS API
# need to complete Orders API later
def orders_get_service_status(c):
    extra_sig_params = {'Action' : 'GetServiceStatus',
                        'Version' : '2013-09-01' }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Orders/2013-09-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Orders/2013-09-01?')
    return None

def orders_list_orders(c):
    return None

def orders_list_orders_by_next_token(c):
    return None

def orders_get_order(c):
    return None

def orders_list_order_items(c):
    return None

def orders_list_order_items_by_next_token(c, next_token):
    return None

# BEGIN SELLERS API
# need to add code for Sellers API later

# BEGIN PRODUCTS API
def products_get_service_status(c):
    extra_sig_params = {'Action' : 'GetServiceStatus',
                        'Version' : '2011-10-01' }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_list_matching_products(c, query, query_context_id = ''):
    #http://docs.developer.amazonservices.com/en_US/products/Products_QueryContextIDs.html
    #the above is a list of QueryContextId values by marketplace
    extra_sig_params = {'Action' : 'ListMatchingProducts',
                        'Version' : '2011-10-01',
                        'Query' : query }
    if query_context_id is not '':
        extra_sig_params.update({'QueryContextId' : query_context_id})
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_matching_product(c, ASINList):
    #ASINList can contain at most 10 ASINs
    extra_sig_params = {'Action' : 'GetMatchingProduct',
                        'Version' : '2011-10-01' }
    ASINDict = {"ASINList.ASIN.{0}".format(i+1):str(j) for (i,j) in enumerate(ASINList)}
    extra_sig_params.update(ASINDict)
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_matching_product_for_id(c, IdType, IdList):
    #IdList can contain at most 5 elements (ASINs, UPCs, ISBNs, etc)
    extra_sig_params = {'Action' : 'GetMatchingProductForId',
                        'Version' : '2011-10-01',
                        'IdType' : IdType }
    IdDict = {"IdList.Id.{0}".format(i+1):str(j) for (i,j) in enumerate(IdList)}
    extra_sig_params.update(IdDict)
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_competitive_pricing_for_sku(c, SKUList):
    extra_sig_params = {'Action' : 'GetCompetitivePricingForSKU',
                        'Version' : '2011-10-01' }
    SKUDict = {"SellerSKUList.SellerSKU.{0}".format(i+1):str(j) for (i,j) in enumerate(SKUList)}
    extra_sig_params.update(SKUDict)
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_competitive_pricing_for_asin(c, ASINList):
    extra_sig_params = {'Action' : 'GetCompetitivePricingForASIN',
                        'Version' : '2011-10-01' }
    ASINDict = {"ASINList.ASIN.{0}".format(i+1):str(j) for (i,j) in enumerate(ASINList)}
    extra_sig_params.update(ASINDict)
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_lowest_offer_listings_for_sku(c, SKUList, exclude_me = 'true', item_condition = ''):
    #though ExcludeMe is an optional param, it is treated as mandatory
    extra_sig_params = {'Action' : 'GetLowestOfferListingsForSKU',
                        'Version' : '2011-10-01',
                        'ExcludeMe' : exclude_me }
    SKUDict = {"SellerSKUList.SellerSKU.{0}".format(i+1):str(j) for (i,j) in enumerate(SKUList)}
    extra_sig_params.update(SKUDict)
    if item_condition is not '':
        extra_sig_params.update({'ItemCondition' : item_condition})
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_lowest_offer_listings_for_asin(c, ASINList, exclude_me = 'true', item_condition = ''):
    #though ExcludeMe is an optional param, it is treated as mandatory
    extra_sig_params = {'Action' : 'GetLowestOfferListingsForASIN',
                        'Version' : '2011-10-01',
                        'ExcludeMe' : exclude_me }
    ASINDict = {"ASINList.ASIN.{0}".format(i+1):str(j) for (i,j) in enumerate(ASINList)}
    extra_sig_params.update(ASINDict)
    if item_condition is not '':
        extra_sig_params.update({'ItemCondition' : item_condition})
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_my_price_for_sku(c, SKUList, item_condition = ''):
    #note that inactive/out-of-stock SKUs will not return price information
    extra_sig_params = {'Action' : 'GetMyPriceForSKU',
                        'Version' : '2011-10-01' }
    SKUDict = {"SellerSKUList.SellerSKU.{0}".format(i+1):str(j) for (i,j) in enumerate(SKUList)}
    extra_sig_params.update(SKUDict)
    if item_condition is not '':
        extra_sig_params.update({'ItemCondition' : item_condition})
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_my_price_for_asin(c, ASINList, item_condition = ''):
    #note that inactive/out-of-stock ASINs will not return price information
    extra_sig_params = {'Action' : 'GetMyPriceForASIN',
                        'Version' : '2011-10-01' }
    ASINDict = {"ASINList.ASIN.{0}".format(i+1):str(j) for (i,j) in enumerate(ASINList)}
    extra_sig_params.update(ASINDict)
    if item_condition is not '':
        extra_sig_params.update({'ItemCondition' : item_condition})
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_product_categories_for_sku(c, sku):
    extra_sig_params = {'Action' : 'GetProductCategoriesForSKU',
                        'Version' : '2011-10-01',
                        'SellerSKU' : sku }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def products_get_product_categories_for_asin(c, asin):
    extra_sig_params = {'Action' : 'GetProductCategoriesForASIN',
                        'Version' : '2011-10-01',
                        'ASIN' : asin }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Products/2011-10-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Products/2011-10-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

# BEGIN RECOMMENDATIONS API
# need to add code for Recommendations API later

# BEGIN SUBSCRIPTIONS API
def subscriptions_get_service_status(c):
    extra_sig_params = {'Action' : 'GetServiceStatus',
                        'Version' : '2013-07-01' }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_register_destination(c, queue_url):
    extra_sig_params = {'Action' : 'RegisterDestination',
                        'Version' : '2013-07-01',
                        'Subscription.Destination.DeliveryChannel' : 'SQS',
                        'Subscription.Destination.AttributeList.member.1.Key' : 'sqsQueueUrl',
                        'Subscription.Destination.AttributeList.member.1.Value' : queue_url }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_deregister_destination(c, queue_url):
    extra_sig_params = {'Action' : 'DeregisterDestination',
                        'Version' : '2013-07-01',
                        'Subscription.Destination.DeliveryChannel' : 'SQS',
                        'Subscription.Destination.AttributeList.member.1.Key' : 'sqsQueueUrl',
                        'Subscription.Destination.AttributeList.member.1.Value' : queue_url }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_list_registered_destinations(c):
    extra_sig_params = {'Action' : 'ListRegisteredDestinations',
                        'Version' : '2013-07-01' }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_send_test_notification_to_destination(c, queue_url):
    extra_sig_params = {'Action' : 'SendTestNotificationToDestination',
                        'Version' : '2013-07-01',
                        'Subscription.Destination.DeliveryChannel' : 'SQS',
                        'Subscription.Destination.AttributeList.member.1.Key' : 'sqsQueueUrl',
                        'Subscription.Destination.AttributeList.member.1.Value' : queue_url }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_create_subscription(c, queue_url, queue_enabled):
    #trying to register a destination SQS queue that is already registered will give a 400 response
    extra_sig_params = {'Action' : 'CreateSubscription',
                        'Version' : '2013-07-01',
                        'Subscription.NotificationType' : 'AnyOfferChanged',
                        'Subscription.Destination.DeliveryChannel' : 'SQS',
                        'Subscription.Destination.AttributeList.member.1.Key' : 'sqsQueueUrl',
                        'Subscription.Destination.AttributeList.member.1.Value' : queue_url,
                        'Subscription.IsEnabled' : queue_enabled }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_get_subscription(c, queue_url):
    extra_sig_params = {'Action' : 'GetSubscription',
                        'Version' : '2013-07-01',
                        'NotificationType' : 'AnyOfferChanged',
                        'Destination.DeliveryChannel' : 'SQS',
                        'Destination.AttributeList.member.1.Key' : 'sqsQueueUrl',
                        'Destination.AttributeList.member.1.Value' : queue_url }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_delete_subscription(c, queue_url):
    extra_sig_params = {'Action' : 'DeleteSubscription',
                        'Version' : '2013-07-01',
                        'NotificationType' : 'AnyOfferChanged',
                        'Destination.DeliveryChannel' : 'SQS',
                        'Destination.AttributeList.member.1.Key' : 'sqsQueueUrl',
                        'Destination.AttributeList.member.1.Value' : queue_url }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_list_subscriptions(c):
    extra_sig_params = {'Action' : 'ListSubscriptions',
                        'Version' : '2013-07-01' }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

def subscriptions_update_subscription(c, queue_url, queue_enabled):
    extra_sig_params = {'Action' : 'UpdateSubscription',
                        'Version' : '2013-07-01',
                        'Subscription.NotificationType' : 'AnyOfferChanged',
                        'Subscription.Destination.DeliveryChannel' : 'SQS',
                        'Subscription.Destination.AttributeList.member.1.Key' : 'sqsQueueUrl',
                        'Subscription.Destination.AttributeList.member.1.Value' : queue_url,
                        'Subscription.IsEnabled' : queue_enabled }
    sig_params_str = build_sig_str(c.access_key, c.secret_key, c.seller_id, c.marketplace_id, extra_sig_params)
    sig_header = "POST\n" + "mws.amazonservices.com\n" + "/Subscriptions/2013-07-01\n"
    url = get_url_with_sig(sig_header, sig_params_str, c.secret_key, '/Subscriptions/2013-07-01?')
    r = post_request2(url, headers=c.user_agent, max_retries=100)
    return r

# the following APIs are newer parts of the MWS API and may have code added for later
# OFF AMAZON PAYMENTS SANDBOX
# OFF AMAZON PAYMENTS
# CART INFORMATION
# CUSTOMER INFORMATION
# WEBSTORE
# FINANCES
# MERCHANT FULFILLMENT

# example use cases for Products API
#print products_get_lowest_offer_listings_for_asin(c=creds, ASINList=['B0000XXXXX'], exclude_me='true', item_condition='').text
#print products_get_my_price_for_asin(c=creds, ASINList=['B0000XXXXX'], item_condition='').text

# example use case for Feeds API - this does a feed to update the prices on SKUs listed in the sku_price dictionary
#sku_price = {'XX-XXXX-XXXX':'9.99'}
#print feeds_submit_feed(creds, feedtype, 'text/xml', sku_price).text

# example use case for making sure any unhandled Exceptions are handled with the general 'Exception' type
#try:
    #print products_get_service_status(creds)
#except requests.exceptions.RequestException:
#except Exception:
    # the exception is already logged in post_request2(.) function
    #pass
