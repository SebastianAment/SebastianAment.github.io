---
layout: page
permalink: /publications/
title: Publications
description: Publications in reversed chronological order. Please also see my Google Scholar profile for a complete list.
years: [2022, 2021, 2019, 2017]
nav: true
nav_order: 2
---
<!-- _pages/publications.md -->
<div class="publications">

{%- for y in page.years %}
  <h2 class="year">{{y}}</h2>
  {% bibliography -f papers -q @*[year={{y}}]* %}
{% endfor %}

</div>
