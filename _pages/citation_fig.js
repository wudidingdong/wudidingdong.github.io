var echarts = require('echarts');

var chartDom = document.getElementById('main');
var myChart = echarts.init(chartDom);
var option;

option = {
  xAxis: {
    type: 'category',
    data: ['2019', '2020', '2021', '2022', '2023']
  },
  yAxis: {
    type: 'value'
  },
  series: [
    {
      data: [1, 2, 7, 36, 8],
      type: 'bar',
      showBackground: true,
      backgroundStyle: {
        color: 'rgba(180, 180, 180, 0.2)'
      }
    }
  ]
};

option && myChart.setOption(option);
