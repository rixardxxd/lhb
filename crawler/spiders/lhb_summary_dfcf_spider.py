import json
import logging
import re
import datetime
from scrapy import Spider, Request

from crawler.items.lhb_summary_dfcf_item import LhbSummaryDfcfItem
from utils.url_dfcf_util import start_urls

logger = logging.getLogger("LhbSummaryDfcfSpider")

class LhbSummaryDfcfSpider(Spider):
    """
    It's the class to crawl cinema info from mtime.com
    """
    name = "lhb_summary_dfcf"
    custom_settings = {
        'ITEM_PIPELINES': {
            'my_scrapy_redis.pipelines.RedisPipeline': 400
        }
    }
    # start_urls = start_urls
    # start_urls = [
    #    'http://data.eastmoney.com/DataCenter_V3/stock2016/TradeDetail/pagesize=200,page=1,sortRule=-1,sortType=,startDate=2015-07-06,endDate=2015-07-06,gpfw=0,js=var%20data_tab_1.html?rt=24545276',
    # ]

    def __init__(self, start_date=None, end_date=None, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # 若输入参数均为None，则默认爬取当天
        # 若输入的参数仅设置了其中一个值，则爬取该值设定的日期
        # 若输入参数都设置了值，则爬取该区间范围的数据
        if start_date is None and end_date is None:
            today = datetime.date.today().strftime("%Y-%m-%d")
            start_date = today
            end_date = today
        elif start_date is None:
            start_date = end_date
        elif end_date is None:
            end_date = start_date

        #  格式化输入参数
        start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

        # 爬取参数设定的区间范围的数据
        self.start_urls = []
        url_format = 'http://data.eastmoney.com/DataCenter_V3/stock2016/TradeDetail/pagesize=200,page=1,sortRule=-1,sortType=,' \
                     'startDate={0},endDate={0},gpfw=0,js=var%20data_tab_1.html?rt=24545276'
        target_date = start_date
        while target_date <= end_date:
            self.start_urls.append(url_format.format(target_date.strftime('%Y-%m-%d')))
            target_date = target_date + datetime.timedelta(1)


    def parse(self, response):
        """
        It's the method to pass the lhb info from response object
        Parameters
        ----------
        response

        Returns
        -------

        """
        # get lhb date
        lhb_date = re.search(r'endDate=(\d{4}-\d{2}-\d{2})', response.url).group(1)
        # get response body
        content_str = response.body_as_unicode()
        # remove the unwanted string in the beginning of the file
        content_str = content_str.split("var data_tab_1=", 1)[1]
        try:
            content = json.loads(content_str)
        except json.decoder.JSONDecodeError as err:
            logger.exception(err)
            return

        # 东方财富接口每次索引最多获取200条记录，如有分页，则生成新的请求URL
        page_index = re.search(r'page=(\d+)', response.url).group(1)
        if content['pages'] > 1 and page_index == '1':
            logger.warn('{0}记录数超过1页：{1}'.format(lhb_date, content['pages']))
            page_index = int(page_index) + 1
            while page_index <= content['pages']:
                next_page = "page=" + str(page_index)
                next_page_url = re.sub(r'page=\d+', next_page, response.url)
                page_index += 1
                yield Request(next_page_url, callback=self.parse)

        # 处理数据部分
        for item in content['data']:
            lhb_item = LhbSummaryDfcfItem()
            lhb_item['lhb_date'] = item['Tdate']
            lhb_item['stock_id'] = item['SCode']
            lhb_item['stock_name'] = item['SName']
            lhb_item['close_price'] = item['ClosePrice']
            lhb_item['change_percent'] = item['Chgradio']
            lhb_item['lhb_net_value'] = item['JmMoney']
            lhb_item['lhb_buy_value'] = item['Bmoney']
            lhb_item['lhb_sell_value'] = item['Smoney']
            lhb_item['lhb_total_value'] = item['ZeMoney']
            lhb_item['trade_amount'] = item['Turnover']
            lhb_item['net_value_percent'] = item['JmRate']
            lhb_item['total_value_percent'] = item['ZeRate']
            lhb_item['turnover_ratio'] = item['Dchratio']
            lhb_item['reason'] = item['Ctypedes']

            # 非A股标的，则直接跳过
            if lhb_item['stock_id'][0] not in ['0', '3', '6']:
                continue
            # 如果龙虎榜买入金额和卖出金额都为空，则数据无效，直接抛弃
            if lhb_item['lhb_buy_value'] == '' and lhb_item['lhb_sell_value'] == '':
                continue

            # 符合条件，则将该item写入redis
            yield lhb_item