# Health Insurance Coverage Gap Analysis

Medicaid is free or low-cost health insurance from the government for people with low incomes. In 2014, states
were given the choice to let more low-income adults sign up for it. This is called Medicaid expansion. Most states
said yes. Ten states still have not.

I wanted to know how many low-income adults still have no health insurance, where they live, and whether things
are different in states that said yes. I used government data for every county in the United States from 2008 to
2023, stored it in a database, checked it, and built a dashboard that anyone can use.

[![Dashboard overview](Image/dashboard_1_overview.png)](dashboard/)

## What I found

- In states that expanded Medicaid in 2014, 37 out of every 100 low-income adults had no health insurance in 2013.
  By 2023 it was 16 out of 100.
- In states that did not expand, it went from 46 out of 100 to 29 out of 100. People in these states are now
  almost twice as likely to have no insurance.
- About 6.5 million low-income adults in the US still had no health insurance in 2023. Half of them live in the
  states that did not expand.
- Texas has the highest share of any state: 40 out of 100 low-income adults have no insurance.
- Hispanic adults are the most likely to be uninsured. In states that did not expand, 46 out of 100 have no
  insurance.
- Big cities and small rural towns improved by about the same amount. What mattered most was whether the state
  expanded.
- Harris County, Texas (Houston) has the most uninsured low-income adults of any county: about 264,000.

"Low-income adults" here means people aged 18 to 64 who earn about $20,000 a year or less.

## What I would suggest

1. Help people sign up. Even in states that expanded, 16 out of 100 low-income adults have no insurance. Many of
   them can probably get Medicaid but have not signed up.
2. Reach Hispanic families in Spanish, since they are the group most likely to be left out.
3. Hospitals in places like Houston, Dallas and El Paso should plan for many patients who cannot pay their bills.
4. The dashboard has a "Find Your County" page, so a hospital or health department can look up its own area.

## The dashboard

The Power BI dashboard has five pages:

| Page | What it shows |
|---|---|
| Overview | The main numbers and the difference between states that did and did not expand |
| States | A map of every state and the states with the most people uninsured |
| Who Is Left Out | Which groups of people are most likely to have no insurance |
| Find Your County | Type any county name and see its numbers and what they mean for local hospitals |
| Data Notes | What the words mean and where the data comes from |

| | |
|---|---|
| ![](Image/dashboard_2_states.png) | ![](Image/dashboard_3_left_out.png) |

![Find your county](Image/dashboard_4_find_your_county.png)

To open it, download this project and open `dashboard/Medicaid_Expansion.pbip` in Power BI Desktop. It does not
need a database.

## Charts

| | |
|---|---|
| ![](Image/01_uninsured_trend_by_group.png) | ![](Image/02_county_map_2023.png) |
| ![](Image/03_state_scorecard.png) | ![](Image/04_income_groups.png) |

## Where the data comes from

| Source | What I used it for |
|---|---|
| [US Census Bureau, Small Area Health Insurance Estimates](https://www.census.gov/programs-surveys/sahie.html) | How many people have no insurance in each county, 2008 to 2023 |
| [KFF, Medicaid expansion decisions](https://www.kff.org/affordable-care-act/issue-brief/status-of-state-medicaid-expansion-decisions/) | Which states expanded, and when |
| [US Census Bureau, poverty and population figures](https://www.census.gov/programs-surveys/saipe.html) | Poverty, income, age and race in each county |
| [US Department of Agriculture, rural-urban codes](https://www.ers.usda.gov/data-products/rural-urban-continuum-codes) | Whether a county is a city, near a city, or rural |

## How I checked the data

- The Census published some of its own 2023 figures in a press release. My database gives exactly the same
  numbers.
- County totals add up exactly to state totals in every year.
- Some counties changed names or codes over the years (for example, all of Connecticut's counties were replaced in
  2022). I matched old and new names so each county has one full history, and left out the few that could not be
  matched.
- Missing values, a few tiny counties, and states that expanded partway through a year were each handled with a
  clear rule, written down in `SQL/02_transform.sql`.

## What to keep in mind

- The Census figures are estimates, so small counties are less exact than big ones.
- States that did and did not expand were already different before 2014, so not all of the gap is caused by
  Medicaid. My companion project measures how much of it is.

## Companion project

[Machine Learning Model for Medicaid Expansion Impact](https://github.com/Isaac-Agyapong/Medicaid_Expansion_Impact_Model)
uses this data to answer two more questions: how much did expansion itself help, and how many more people would
have insurance if the remaining states expanded? It includes a web app.

## Tools used

PostgreSQL (star schema, window functions, CTEs, materialized views, data quality checks), Python (pandas,
matplotlib, psycopg, Jupyter), Power BI (DAX, Power Query, report built from code as a PBIP project).

## How to rebuild it

1. Install Python 3.13 and PostgreSQL 18, then run `pip install -r requirements.txt`.
2. Run `python run_all.py`. It downloads the data, builds the database, runs the checks and rebuilds the charts and
   dashboard (about 5 minutes after the download).

---

Built by Isaac Agyapong · [GitHub](https://github.com/Isaac-Agyapong)
