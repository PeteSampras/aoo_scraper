database_base_path = "../aoodata.github.io/data/"
world = "385"
alliances = ["DAY", "GFX", "TOD"]
report_path = "reports/template/reports/"
duration_days = 80

from utils import *
from recordclass import RecordClass
import pandas as pd
class RankingConfig(RecordClass):
    ranked: bool
    diffable: bool


used_rankings = {
        "commander_officer": RankingConfig(True, True),
        "commander_titan": RankingConfig(True, True),
        "commander_warplane": RankingConfig(True, True),
        "commander_island": RankingConfig(True, True),
        "commander_kill": RankingConfig(True, True),
        "commander_reputation": RankingConfig(False, True),
        "commander_merit": RankingConfig(True, True),

        }

def get_all_commander_aliases(cursor, commander_id, ref_timestamp, begin_timestamp):
    query = ("select name from commander_names where commander_id = ? and (date <= ? and date >= ?)", (commander_id, ref_timestamp, begin_timestamp))
    cursor.execute(*query)
    names = cursor.fetchall()
    if len(names) == 0:
        return ""
    return ", ".join([x[0] for x in names])

def get_ke_stats_commander(cursor, commander_id, ref_timestamp, ranking, before):
    collection_id = get_collection_id(cursor, ranking, ref_timestamp, before)
    if collection_id is None:
        return None
    query = ("select value, rank from commander_ranking_data where commander_id = ? and data_collection_id = ?", (commander_id, collection_id))
    cursor.execute(*query)
    res = cursor.fetchone()
    return res

ke_rankings = {
    "void": ["commander_kill", "commander_reputation"],
    "frenzy": [],
}

def get_ke_stats(cursor, commander_id, event_date, event_type):
    timestamp = date_to_timestamp(event_date)
    result = {}

    base_ranking = "commander_ke_" + event_type
    result["commander_ke"] = get_ke_stats_commander(cursor, commander_id, timestamp, base_ranking, False)

    rankings = ke_rankings[event_type]

    reputation_reset = False
    if (event_date.month == 1 and event_date.day == 1) or (event_date.month == 12 and event_date.day == 31):
        reputation_reset = True

    for ranking in rankings:
        res_before = get_ke_stats_commander(cursor, commander_id, timestamp, ranking, True)
        res_after = get_ke_stats_commander(cursor, commander_id, timestamp, ranking, False)
        if res_before is not None and res_after is not None:
            if reputation_reset and ranking == "commander_reputation":
                result[ranking] = res_after[0]
            else:
                result[ranking] = res_after[0] - res_before[0]
    return result

def get_all_ke_stats(cursor, commander_id, ref_date, begin_date, event_type):
    results = []
    current_date = get_date_of_first_strongest_commander_event_before(ref_date, event_type)["date"]
    while current_date > begin_date:
        res = get_ke_stats(cursor, commander_id, current_date, event_type)
        if res is not None:
            results.append(res)
        current_date = current_date - datetime.timedelta(days=7)
        current_date = get_date_of_first_strongest_commander_event_before(current_date, event_type)["date"]
    return results


def agregate_ke_stats(stats, event_type):
    result = {}
    rankings = ke_rankings[event_type]
    num_events = len(stats)

    ranking = "commander_ke"
    mean_score = 0
    mean_rank = 0
    num_ranked = 0
    for i in range(num_events):
        v = stats[i][ranking]
        if v is not None:
            num_ranked += 1
            mean_score += v[0]
            mean_rank += v[1]
    result["commander_ke_" + event_type + "_mean_ranked_score"] = (mean_score / num_ranked) if num_ranked > 0 else None
    result["commander_ke_" + event_type + "_mean_ranked_rank"] = (mean_rank / num_ranked) if num_ranked > 0 else None
    result["commander_ke_" + event_type + "_num_ranked"] = num_ranked
    result["commander_ke_" + event_type + "_num_events"] = num_events

    for ranking in rankings:
        score = 0
        for i in range(num_events):
            if ranking not in stats[i]:
                continue
            v = stats[i][ranking]
            if v is not None:
                score += v
        result["commander_ke_" + event_type + "_" + ranking] = score
        #result[ranking] = result[ranking] / num_events

    return result

def get_commander_ranking_data(cursor, commander_id, ranking, timestamp, reversable=False, begin_limit=None):
    collection_id, timestamp = get_collection_id(cursor, ranking, timestamp, True, True)
    is_valid_timestamp = begin_limit is None or timestamp > begin_limit
    if collection_id is None:
        return None
    query = ("select value, rank from commander_ranking_data where commander_id = ? and data_collection_id = ?", (commander_id, collection_id))
    cursor.execute(*query)
    res = cursor.fetchone()

    if res is not None and is_valid_timestamp:
        return res[0], res[1], timestamp
    if not reversable:
        return None
    # search after timestamp
    query = ("select value, rank, date from commander_ranking_data, data_collections "
             "where commander_id = ? and data_collection_id = data_collections.id "
             "and type_id = ? and date > ? order by date asc limit 1",
             (commander_id, collection_type_id[ranking], timestamp))
    cursor.execute(*query)
    res = cursor.fetchone()
    return res

def get_commander_ranking_data_diff(cursor, commander_id, ranking, ref_timestamp, begin_timestamp, begin_limit):
    ref_data = get_commander_ranking_data(cursor, commander_id, ranking, ref_timestamp)
    begin_data = get_commander_ranking_data(cursor, commander_id, ranking, begin_timestamp, True, begin_limit)
    if ref_data is None or begin_data is None:
        return None

    value_progression = ref_data[0], ref_data[0] - begin_data[0]
    rank_progression = (ref_data[1], begin_data[1] - ref_data[1]) if ref_data[1] != -1 and begin_data[1] != -1 else None
    first_measurement_date = begin_data[2]
    return value_progression, rank_progression, first_measurement_date

def get_commander_rankings_data(cursor, commander_id, ref_timestamp, begin_timestamp, begin_limit):
    result = {}
    for ranking in used_rankings:
        if used_rankings[ranking].diffable:
            result[ranking] = get_commander_ranking_data_diff(cursor, commander_id, ranking, ref_timestamp, begin_timestamp, begin_limit)
        else:
            result[ranking] = get_commander_ranking_data(cursor, commander_id, ranking, ref_timestamp)
    return result


def get_commander_first_collection_date(cursor, commander_id, begin_timestamp, begin_limit=None):
    # try to find the first collection date for the commander before the begin_timestamp
    query = ("select date from data_collections, commander_ranking_data "
             "where commander_id = ? and data_collections.id = data_collection_id and date < ? order by date desc limit 1", (commander_id, begin_timestamp))
    cursor.execute(*query)
    res = cursor.fetchone()

    if res is not None and (begin_limit is None or res[0] > begin_limit):
        return res[0]
    # if not found, try to find the first collection date after the begin_timestamp
    query = ("select date from data_collections, commander_ranking_data "
             "where commander_id = ? and data_collections.id = data_collection_id and date > ? order by date asc limit 1", (commander_id, begin_timestamp))
    cursor.execute(*query)
    res = cursor.fetchone()
    if res is not None:
        return res[0]
    return None


def get_commanders_rankings_data(cursor, commanders, ref_date, begin_date, begin_limit):
    ref_timestamp = date_to_timestamp(ref_date)
    begin_timestamp = date_to_timestamp(begin_date)

    result = {}
    for commander, commander_id in commanders:
        res = get_commander_rankings_data(cursor, commander_id, ref_timestamp, begin_timestamp, begin_limit)
        res["commander_first_collection_date"] = get_commander_first_collection_date(cursor, commander_id, begin_timestamp, begin_limit)
        res.update(agregate_ke_stats(get_all_ke_stats(cursor, commander_id, ref_date, begin_date, "void"), "void"))
        res.update(agregate_ke_stats(get_all_ke_stats(cursor, commander_id, ref_date, begin_date, "frenzy"), "frenzy"))
        res["commander_aliases"] = get_all_commander_aliases(cursor, commander_id, ref_timestamp, begin_timestamp)
        result[commander] = res

        if res["commander_reputation"] is not None: # fix reputation reset on new year
            first_collection_date = timestamp_to_date(res["commander_reputation"][2])
            if first_collection_date.year < ref_date.year:
                res["commander_reputation"] = ((res["commander_reputation"][0][0], res["commander_reputation"][0][0]), None, res["commander_reputation"][2])

    return result


def get_timestamp_of_closest_collection(cursor, timestamp, before):
    collection_id = collection_type_id["commander_loss"]
    if before:
        cursor.execute("select date from data_collections where type_id = ? and date < ? order by date desc limit 1", (collection_id, timestamp))
        before = cursor.fetchone()[0]
        return before
    else:
        cursor.execute("select date from data_collections where type_id = ? and date > ? order by date asc limit 1", (collection_id, timestamp))
        after = cursor.fetchone()[0]
        return after

def get_latest_collection_id(cursor, ref_date):
    return get_collection_id(cursor, "commander_loss", ref_date, True)

def get_alliance_members(cursor, alliance_names, ref_date):
    # test if alliance_name is a string
    if isinstance(alliance_names, str):
        alliance_names = (alliance_names.lower(),)
    else:
        alliance_names = tuple([x.lower() for x in alliance_names])
    latest_collection_id = get_latest_collection_id(cursor, ref_date)
    query = ("select commanders.canonical_name, commander_id " +
             "from commanders, commander_ranking_data, alliances " +
             "where commanders.alliance_id = alliances.id " +
             "and commanders.id = commander_ranking_data.commander_id " +
             "and alliances.name_short in (" + ",".join('?'*len(alliance_names)) + ") " +
             "and commander_ranking_data.data_collection_id = ?", (*alliance_names, latest_collection_id))

    cursor.execute(*query)
    return cursor.fetchall()


def flatten_commanders_rankings_data(data):
    result = []
    for commander, stats in data.items():
        stats["commander"] = commander
        for ranking, config in used_rankings.items():
            value = None
            value_diff = None
            rank = None
            rank_diff = None
            first_measure_timestamp = None
            if stats[ranking] is not None:
                data_value, data_rank, first_measure_timestamp = stats[ranking]
                value = data_value[0]
                value_diff = data_value[1]

                if data_rank is not None:
                    rank = data_rank[0]
                    rank_diff = data_rank[1]
            stats[ranking + "_value"] = value
            stats[ranking + "_value_diff"] = value_diff
            stats[ranking + "_first_measure_timestamp"] = first_measure_timestamp
            if config.ranked:
                stats[ranking + "_rank"] = rank
                stats[ranking + "_rank_diff"] = rank_diff

            del stats[ranking]


        result.append(stats)
    return result

def report(dbFile, ref_date, world, alliances, duration, path):
    import sqlite3
    import math
    conn = sqlite3.connect(dbFile)
    c = conn.cursor()

    # add 1 day to the ref_date to get the last collection of the day
    ref_date = ref_date + datetime.timedelta(days=1)

    ref_timestamp = date_to_timestamp(ref_date)

    # 1 month before
    #begin_date = ref_date - datetime.timedelta(days=27)
    begin_date = ref_date - datetime.timedelta(days=duration)
    begin_timestamp = date_to_timestamp(begin_date)


    alliance_members = get_alliance_members(c, alliances, ref_timestamp)

    last_collection_timestamp = get_timestamp_of_closest_collection(c, ref_timestamp, True)
    last_collection_date = timestamp_to_date(last_collection_timestamp)

    first_collection_timestamp = get_timestamp_of_closest_collection(c, begin_timestamp, True)
    first_collection_date = timestamp_to_date(first_collection_timestamp)

    duration = round((last_collection_timestamp - first_collection_timestamp) / (24 * 3600))

    data = get_commanders_rankings_data(c, alliance_members, ref_date, begin_date, first_collection_timestamp - 3600*11)
    data = flatten_commanders_rankings_data(data)

    num_void = data[0]["commander_ke_void_num_events"]
    num_frenzy = data[0]["commander_ke_frenzy_num_events"]

    ref_date = last_collection_date

    df = pd.DataFrame(data)
    df["commander_kill_without_void"] = df['commander_kill_value_diff'] - df['commander_ke_void_commander_kill']
    df["commander_duration"] = ((last_collection_timestamp - df["commander_first_collection_date"]) / (24 * 3600)).round()
    #df["commander_duration"] = df["commander_duration"].replace(duration, None)

    for ranking in used_rankings:
        df[ranking + "_duration"] = pd.to_numeric(((last_collection_timestamp - df[ranking + "_first_measure_timestamp"]) / (24 * 3600))).round()

    df = df.astype(
        {
            'commander_duration': "Int64",
            'commander_merit_value': 'Int64',
            'commander_merit_value_diff': 'Int64',
            'commander_merit_rank': 'Int64',
            'commander_merit_rank_diff': 'Int64',
            'commander_merit_duration': 'Int64',
            'commander_reputation_value': 'Int64',
            'commander_reputation_value_diff': 'Int64',
            'commander_reputation_duration': 'Int64',
            'commander_kill_without_void': 'Int64',
            'commander_kill_duration': 'Int64',
            'commander_officer_value': 'Int64',
            'commander_officer_value_diff': 'Int64',
            'commander_officer_rank': 'Int64',
            'commander_officer_rank_diff': 'Int64',
            'commander_officer_duration': 'Int64',
            'commander_titan_value': 'Int64',
            'commander_titan_value_diff': 'Int64',
            'commander_titan_rank': 'Int64',
            'commander_titan_rank_diff': 'Int64',
            'commander_titan_duration': 'Int64',
            'commander_warplane_value': 'Int64',
            'commander_warplane_value_diff': 'Int64',
            'commander_warplane_rank': 'Int64',
            'commander_warplane_rank_diff': 'Int64',
            'commander_warplane_duration': 'Int64',
            'commander_island_value': 'Int64',
            'commander_island_value_diff': 'Int64',
            'commander_island_rank': 'Int64',
            'commander_island_rank_diff': 'Int64',
            'commander_island_duration': 'Int64',
            'commander_ke_void_mean_ranked_score': 'Int64',
            'commander_ke_void_mean_ranked_rank': 'Int64',
            'commander_ke_void_num_ranked': 'Int64',
            'commander_ke_void_num_events': 'Int64',
            'commander_ke_void_commander_kill': 'Int64',
            'commander_ke_void_commander_reputation': 'Int64',
            'commander_ke_frenzy_mean_ranked_score': 'Int64',
            'commander_ke_frenzy_mean_ranked_rank': 'Int64',
            'commander_ke_frenzy_num_ranked': 'Int64',
            'commander_ke_frenzy_num_events': 'Int64',
            'commander_kill_value': 'Int64',
            'commander_kill_value_diff': 'Int64',
            'commander_kill_rank': 'Int64',
            'commander_kill_rank_diff': 'Int64'}, errors='ignore')


    cols = ['commander', 'commander_aliases','commander_duration',
            'commander_merit_value', 'commander_merit_value_diff', 'commander_merit_rank', 'commander_merit_rank_diff', 'commander_merit_duration',
            'commander_reputation_value', 'commander_reputation_value_diff', 'commander_reputation_duration',
            'commander_kill_without_void', 'commander_kill_duration',
            'commander_officer_value', 'commander_officer_value_diff', 'commander_officer_rank', 'commander_officer_rank_diff', 'commander_officer_duration',
            'commander_titan_value', 'commander_titan_value_diff', 'commander_titan_rank', 'commander_titan_rank_diff', 'commander_titan_duration',
            'commander_warplane_value', 'commander_warplane_value_diff', 'commander_warplane_rank', 'commander_warplane_rank_diff', 'commander_warplane_duration',
            'commander_island_value', 'commander_island_value_diff', 'commander_island_rank','commander_island_rank_diff', 'commander_island_duration',
            'commander_ke_void_mean_ranked_rank', 'commander_ke_void_num_ranked', #'commander_ke_void_mean_ranked_score', 'commander_ke_void_mean_ranked_rank', 'commander_ke_void_num_ranked', 'commander_ke_void_num_events', 'commander_ke_void_commander_kill', 'commander_ke_void_commander_reputation',
            'commander_ke_frenzy_mean_ranked_rank', 'commander_ke_frenzy_num_ranked',#'commander_ke_frenzy_mean_ranked_score', 'commander_ke_frenzy_mean_ranked_rank', 'commander_ke_frenzy_num_ranked', 'commander_ke_frenzy_num_events',
            #'commander_kill_value', 'commander_kill_value_diff', 'commander_kill_rank', 'commander_kill_rank_diff',
            ]

    df = df[cols]

    html = df.to_html(index=False, float_format='%.2f', na_rep="", table_id="table_id", classes="table table-striped table-bordered compact")

    filename = "report_" + str(world) + "_" + ref_date.strftime("%Y-%m-%d") + "_(" +"_".join(alliances) + ").html"

    with open(path + filename, "w", encoding='utf-8') as f:
        f.write(create_header(world, alliances, ref_date, duration, num_void, num_frenzy))
        f.write(html)
        f.write(create_footer(df, duration, num_void, num_frenzy))

    conn.close()
    #print("done")
    return filename

def create_header(world, alliances, date, duration, num_void, num_frenzy):

    header = """
    <!DOCTYPE html>
    <html>
    <head>
    <title>AOO Report</title>
    <meta charset="utf-8">
    <meta name="format-detection" content="telephone=no">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.datatables.net/v/bs5/jq-3.7.0/dt-1.13.10/b-2.4.2/b-colvis-2.4.2/b-html5-2.4.2/cr-1.7.0/fc-4.3.0/fh-3.4.0/sr-1.3.0/datatables.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
    <style>
        [data-tooltip] {
         cursor: pointer;
         display: inline-block;
         line-height: 1;
         position: relative;
    }
     [data-tooltip]::after {
         background-color: rgba(51, 51, 51, .9);
         border-radius: 0.3rem;
         color: #fff;
         content: attr(data-tooltip);
         font-size: 1rem;
         font-size: 85%;
         font-weight: normal;
         line-height: 1.15rem;
         opacity: 0;
         padding: 0.25rem 0.5rem;
         position: absolute;
         text-align: center;
         text-transform: none;
         transition: opacity 0.2s;
         visibility: hidden;
         white-space: nowrap;
         z-index: 1;
    }
     [data-tooltip].tooltip-top::before {
         border-style: solid;
         border-width: 0.3rem;
         content: "";
         opacity: 0;
         position: absolute;
         transition: opacity 0.2s;
         visibility: hidden;
         border-color: rgba(51, 51, 51, .9) transparent transparent transparent;
         top: 0;
         left: 50%;
         margin-left: -0.3rem;
    }
     [data-tooltip].tooltip-top::after {
         bottom: 100%;
         left: 50%;
         transform: translate(-50%);
    }
     [data-tooltip].tooltip-bottom::before {
         border-style: solid;
         border-width: 0.3rem;
         content: "";
         opacity: 0;
         position: absolute;
         transition: opacity 0.2s;
         visibility: hidden;
         border-color: transparent transparent rgba(51, 51, 51, .9) transparent;
         bottom: 0;
         left: 50%;
         margin-left: -0.3rem;
    }
     [data-tooltip].tooltip-bottom::after {
         top: 100%;
         left: 50%;
         transform: translate(-50%);
    }
     [data-tooltip].tooltip-left::before {
         border-style: solid;
         border-width: 0.3rem;
         content: "";
         opacity: 0;
         position: absolute;
         transition: opacity 0.2s;
         visibility: hidden;
         border-color: transparent transparent transparent rgba(51, 51, 51, .9);
         top: 0.3rem;
         right: calc(110% - 0.3rem);
         margin-top: -0.3rem;
    }
     [data-tooltip].tooltip-left::after {
         top: -0.3rem;
         right: calc(110% + 0.3rem);
    }
     [data-tooltip].tooltip-right::before {
         border-style: solid;
         border-width: 0.3rem;
         content: "";
         opacity: 0;
         position: absolute;
         transition: opacity 0.2s;
         visibility: hidden;
         border-color: transparent rgba(51, 51, 51, .9) transparent transparent;
         top: 50%;
         top: 0.3rem;
         left: calc(110% - 0.3rem);
         margin-top: -0.3rem;
    }
     [data-tooltip].tooltip-right::after {
         top: -0.3rem;
         left: calc(110% + 0.3rem);
    }
     @media (max-width: 767px) {
         [data-tooltip].tooltip-mobile::before {
             display: none;
        }
         [data-tooltip].tooltip-mobile:after {
             font-size: 1rem;
             max-width: 20rem;
             position: fixed;
             bottom: auto;
             top: 50%;
             left: 50%;
             text-align: left;
             transform: translate(-50%);
             white-space: normal;
        }
    }
     [data-tooltip]:hover::after, [data-tooltip][class*=tooltip-]:hover::before {
         visibility: visible;
         opacity: 1;
    }
    </style>
    </head>
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.datatables.net/v/bs5/jq-3.7.0/dt-1.13.10/b-2.4.2/b-colvis-2.4.2/b-html5-2.4.2/cr-1.7.0/fc-4.3.0/fh-3.4.0/sr-1.3.0/datatables.min.js"></script>
    <!--<script src="https://cdn.jsdelivr.net/gh/tomickigrzegorz/circular-progress-bar@1.2.0/dist/circularProgressBar.min.js"></script>-->
    <body>
    <img style="position: absolute;right: 10px;margin: 10px;width: 50px;height: 50px;" title="MaxBlunt 385" alt="MaxBlunt 385" src='data:image/png;base64,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'></img>
    <h1 style="text-align: center;">World """ + str(world) + """ - """ + ", ".join(alliances) + """</h1>
    <h2 style="text-align: center;">""" + date.strftime("%d-%m-%Y") + """ - """ + str(duration) + """ days</h2>
    <h3 style="text-align: center;">""" + str(num_void) + """ voids - """ + str(num_frenzy) + """ frenzies</h3>
    """
    return header


def create_column_def(data, index, title, ranked, normal_duration):
    # first quartile of column index
    #q1 = data.iloc[:, index+1].quantile(0.25)

    desc = """{
                title: '""" + title + """',
                render: function(data, type, row){
                    return render_score_cell(data, type, row, """ + str(index) + """, """ + str(ranked).lower() + """, """ + str(normal_duration) + """);
                },
                type: 'num',
                orderData: [""" + str(index + 1) + """, """ + str(index) + """],
                searchable: false
            },
            { visible: false, searchable: false, type: 'num' },
            { visible: false, searchable: false, type: 'num' },
            """
    if ranked:
        desc += "{ visible: false, searchable: false, type: 'num' },\n"
        desc += "{ visible: false, searchable: false, type: 'num' },\n"
    return desc



def create_footer(data, normal_duration, num_void, num_frenzy):

    columns_def = ""
    columns_def += """{
                title: "Name",
                 render: function(data, type, row){
                    var res;
                    if (true || row[2] == """ + str(normal_duration) + """)
                    {  res = "<div><b>" + data + "</b></div>"; }
                    else { res = "<div><b>" + data + "</b> (" + row[2] + " days)</div>"; }
                    if (row[1] !== "")
                        res += '<div style="font-size: 70%; padding-left: 10px;padding-top: 6px; max-width: 20em;">Previous: ' + row[1] + '</div>';
                    
                    return res;
                    },
                searchable: true
            },
            { visible: false, searchable: true },
            { visible: false },
            """
    curIndex = 3
    columns_def += create_column_def(data, curIndex, "Merit", True, normal_duration)
    curIndex += 5
    columns_def += create_column_def(data, curIndex, "Reputation", False, normal_duration)
    curIndex += 3
    columns_def += """
            {
                title: `Kills 
                        <span style="padding-left:10px;" class="tooltip-right tooltip-mobile" data-tooltip="Does not include void kills. Measures involvement in nation cleaning.">
                        <i class="fas fa-question-circle" focusable="false" aria-hidden="true"></i></span>`,
                render: function(data, type, row){
                    if (type !== "display") return parseFloat(data);
                    if (data === "&lt;NA&gt;" || data === "")
                        return "";
                    var res = "<div style='position: relative; width:100%; height: 100%;'>" + formatScore(parseFloat(data));
                    var duration = parseFloat(row[""" + str(curIndex + 1) + """]);
                    res += duration_check_indicator(duration, """ + str(normal_duration) + """);
                    res += "</div>";
                    return res;
                },
                type: 'num',
                searchable: false
            },
            { visible: false, searchable: false, type: 'num' },
            """
    curIndex += 2
    columns_def += create_column_def(data, curIndex, "Officer", True, normal_duration)
    curIndex += 5
    columns_def += create_column_def(data, curIndex, "Titan", True, normal_duration)
    curIndex += 5
    columns_def += create_column_def(data, curIndex, "Warplane", True, normal_duration)
    curIndex += 5
    columns_def += create_column_def(data, curIndex, "Island", True, normal_duration)
    curIndex += 5
    columns_def += """
            {
                title: `Void rank 
                        <span style="padding-left:10px;" class="tooltip-left tooltip-mobile" data-tooltip="TOP100 rate and average rank. Measures performance, not activity.">
                        <i class="fas fa-question-circle" focusable="false" aria-hidden="true"></i></span>`,
                render: function(data, type, row){
                    var valid = !(data === "&lt;NA&gt;" || data === "");
                    if (type !== "display") return (valid)?parseFloat(data):101;
                    if (!valid)
                        return "";
                    
                    var res = '<div style="display: inline-block;margin-top: 14px;">' + formatScore(parseFloat(data)) + "</div>";
                    var num_ranked = parseFloat(row[""" + str(curIndex + 1) + """]);
                    var percent_ranked = Math.round(num_ranked / """ + str(num_void) + """ * 100, 0);
                    res +=  '<div style="float: right;"><div class="pie"  data-pie=\\'{ "round": true, "percent": ' + percent_ranked + ', "colorSlice": "#5cadff", "time": 10, "size": 50 }\\'></div></div>';
                    return res;
                },
                orderData: [""" + str(curIndex + 1) + """, """ + str(curIndex) + """],
                type: 'num',
                searchable: false
            },
            { visible: false, searchable: false, type: 'num' },"""
    curIndex += 2
    columns_def += """
            {
                title: `Frenzy rank 
                        <span style="padding-left:10px;" class="tooltip-left tooltip-mobile" data-tooltip="TOP100 rate and average rank. Measures performance, not activity.">
                        <i class="fas fa-question-circle" focusable="false" aria-hidden="true"></i></span>`,
                render: function(data, type, row){
                    var valid = !(data === "&lt;NA&gt;" || data === "");
                    if (type !== "display") return (valid)?parseFloat(data):101;
                    if (!valid)
                        return "";
                    
                    var res = '<div style="display: inline-block;margin-top: 14px;">' + formatScore(parseFloat(data)) + "</div>";
                    var num_ranked = parseFloat(row[""" + str(curIndex + 1) + """]);
                    var percent_ranked = Math.round(num_ranked / """ + str(num_frenzy) + """ * 100, 0);
                    res +=  '<div style="float: right;"><div class="pie"  data-pie=\\'{ "round": true, "percent": ' + percent_ranked + ', "colorSlice": "#5cadff", "time": 10, "size": 50 }\\'></div></div>';
                    return res;
                },
                orderData: [""" + str(curIndex + 1) + """, """ + str(curIndex) + """],
                type: 'num',
                searchable: false
            },
            { visible: false, searchable: false, type: 'num' },"""
    curIndex += 2




    footer = """
    <!-- footer -->
    <div style="text-align: center;margin-top:30px;">MaxBlunt (#385)</div>
    
    <!-- scripts -->
    <script>
    var CircularProgressBar=function(){"use strict";const t={colorSlice:"#00a1ff",fontColor:"#000",fontSize:"1.6rem",fontWeight:400,lineargradient:!1,number:!0,round:!1,fill:"none",unit:"%",rotation:-90,size:200,stroke:10},e=({rotation:t,animationSmooth:e})=>`transform:rotate(${t}deg);transform-origin: 50% 50%;${e?"transition: stroke-dashoffset "+e:""}`,n=t=>({"stroke-dasharray":t||"264"}),o=({round:t})=>({"stroke-linecap":t?"round":""}),r=t=>({"font-size":t.fontSize,"font-weight":t.fontWeight}),i=t=>document.querySelector(t),s=(t,{lineargradient:e,index:n,colorSlice:o})=>{t.setAttribute("stroke",e?`url(#linear-${n})`:o)},a=(t,e)=>{for(const n in e)null==t||t.setAttribute(n,e[n])},c=t=>document.createElementNS("http://www.w3.org/2000/svg",t),l=(t,e)=>{const n=c("tspan");return n.classList.add(t),e&&(n.textContent=e),n},d=(t,e,n)=>{const o=264-t/100*(n?2.64*(100-n):264);return e?-o:o},f=(t,e,n="beforeend")=>t.insertAdjacentElement(n,e);return class{constructor(t,e={}){this.t=t,this.o=e;const n=document.querySelectorAll("."+t),o=[].slice.call(n);o.map(((t,n)=>{const o=JSON.parse(t.getAttribute("data-pie"));t.setAttribute("data-pie-index",o.index||e.index||n+1)})),this.i=o}initial(t){const e=t||this.i;Array.isArray(e)?e.map((t=>this.l(t))):this.l(e)}h(t,d,h){const u=this.t;h.number&&f(t,((t,e)=>{const n=c("text");n.classList.add(`${e}-text-${t.index}`),f(n,l(`${e}-percent-${t.index}`)),f(n,l(`${e}-unit-${t.index}`,t.unit));const o={x:"50%",y:"50%",fill:t.fontColor,"text-anchor":"middle",dy:t.textPosition||"0.35em",...r(t)};return a(n,o),n})(h,u));const m=i(`.${u}-circle-${h.index}`),$={fill:"none","stroke-width":h.stroke,"stroke-dashoffset":"264",...n(),...o(h)};a(m,$),this.animationTo({...h,element:m},!0),m.setAttribute("style",e(h)),s(m,h),d.setAttribute("style",`width:${h.size}px;height:${h.size}px;`)}animationTo(e,n=!1){const o=this.t,c=JSON.parse(i(`[data-pie-index="${e.index}"]`).getAttribute("data-pie")),l=i(`.${o}-circle-${e.index}`);if(!l)return;const f=n?e:{...t,...c,...e,...this.o};if(n||s(l,f),!n&&f.number){const t={fill:f.fontColor,...r(f)},e=i(`.${o}-text-${f.index}`);a(e,t)}const h=i(`.${o}-percent-${e.index}`);if(f.animationOff)return f.number&&(h.textContent=""+f.percent),void l.setAttribute("stroke-dashoffset",d(f.percent,f.inverse));let u=JSON.parse(l.getAttribute("data-angel"));const m=Math.round(e.percent);if(0===m&&(f.number&&(h.textContent="0"),l.setAttribute("stroke-dashoffset","264")),m>100||m<0||u===m)return;let $,p=n?0:u;const g=1e3/(f.speed||1e3);let x=performance.now();const k=t=>{$=requestAnimationFrame(k);const e=t-x;e>=g-.1&&(x=t-e%g,u>=f.percent?p--:p++),l.setAttribute("stroke-dashoffset",d(p,f.inverse,f.cut)),h&&f.number&&(h.textContent=""+p),l.setAttribute("data-angel",p),l.parentNode.setAttribute("aria-valuenow",p),p===m&&cancelAnimationFrame($)};requestAnimationFrame(k)}l(e){const n=e.getAttribute("data-pie-index"),o=JSON.parse(e.getAttribute("data-pie")),r={...t,...o,index:n,...this.o},i=c("svg"),s={role:"progressbar",width:r.size,height:r.size,viewBox:"0 0 100 100","aria-valuemin":"0","aria-valuemax":"100"};a(i,s),r.colorCircle&&i.appendChild(this.u(r)),r.lineargradient&&i.appendChild((({index:t,lineargradient:e})=>{const n=c("defs"),o=c("linearGradient");o.id="linear-"+t;const r=[].slice.call(e);n.appendChild(o);let i=0;return r.map((t=>{const e=c("stop");a(e,{offset:i+"%","stop-color":""+t}),o.appendChild(e),i+=100/(r.length-1)})),n})(r)),i.appendChild(this.u(r,"top")),e.appendChild(i),this.h(i,e,r)}u(t,r="bottom"){const i=c("circle");let s={};if(t.cut){const r=264-2.64*(100-t.cut);s={"stroke-dashoffset":t.inverse?-r:r,style:e(t),...n(),...o(t)}}const l={fill:t.fill,stroke:t.colorCircle,"stroke-width":t.strokeBottom||t.stroke,...s};t.strokeDasharray&&Object.assign(l,{...n(t.strokeDasharray)});const d={cx:"50%",cy:"50%",r:42,"shape-rendering":"geometricPrecision",..."top"===r?{class:`${this.t}-circle-${t.index}`}:l};return a(i,d),i}}}();

    
    function formatScore(score, forceSign=false) {
        // add commas to the score
        var res = score.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        if (forceSign && score > 0) {
            return "+" + res;
        } 
        return res;
    }
    
    function duration_check_indicator(duration, normal_duration){
        var res = "";
        if (duration !== normal_duration){
            var diff = duration;
            res += '<span  style="position: absolute; right: 5px; top: 5px; font-size:80%; color: #cdae02;" class="tooltip-top tooltip-mobile" data-tooltip="Only covers a ' + diff + '-day period.">' +
                        '<i class="fa-solid fa-triangle-exclamation" focusable="false" aria-hidden="true"></i></span>'; //style="position: absolute; right: 10px"
        }
        return res;
    }
    
    function render_score_cell(data, type, row, index, ranked, normal_duration){
        if (type !== "display") 
            return parseFloat(data);
        var value = row[index];
        var value_diff = parseFloat(row[index + 1]);
        if (value === "&lt;NA&gt;") 
            return "";
        var evolution = (value_diff !== 0)? formatScore(value_diff, true): "-";
        var res = "<div style='position: relative; width:100%; height: 100%;'><div>" + formatScore(parseFloat(value)) + " (" + evolution + ")</div>";
        if (ranked){
            var rank = row[index+  2];
            var rank_diff = row[index + 3];
            if (rank !== "&lt;NA&gt;") 
            {
                var rankdiff = parseFloat(rank_diff);
                if (rankdiff == 0)
                    { res += "<div>" + rank + " (-)</div>"; }
                else {
                    res += "<div>" + rank + " (<span style=\'color:" + (rankdiff > 0 ? "green" : "red") + ";\'>" + formatScore(rankdiff, true) + "</span>)</div>";
                }
            }
        }
        var duration = parseFloat((ranked)?row[index + 4]:row[index + 2]);
        res += duration_check_indicator(duration, normal_duration);
        res += "</div>"; 
        return res;
    }
    
    $(document).ready( function () {
        $('#table_id').DataTable({
            //stateSave: true,
            paging: false,
            fixedHeader: true,
            fixedColumns: true,
            order: [[ 3, "desc" ]],
            columns: [
                    """ + columns_def + """
                    ],
            });  
        const circle = new CircularProgressBar("pie");
        circle.initial();    
        } );
    </script>
    </body>
    </html>
    """

    return footer


if __name__ == "__main__":
    import datetime
    base = "reports/"
    path = base

    database_base_path = "../aoodata.github.io/data/"

    for alliance in alliances:
        file = report(database_base_path + world + "DB.sqlite", datetime.date.today(), int(world), [alliance], duration_days, path)
        print("report created: " + path + file)