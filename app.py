import flask
from flask import Flask, render_template, request, session, redirect
from flask_session import Session
from flask_bootstrap import Bootstrap
import pandas as pd
from InstagramAPI import InstagramAPI
import csv
import networkx as nx
import numpy as np
from tqdm import tqdm
import time
import datetime
from io import BytesIO
from PIL import Image
import requests
import os

app = Flask(__name__)
SESSION_TYPE = 'filesystem'
PERMANENT_SESSION_LIFETIME = 1800
app.config.update(SECRET_KEY=os.urandom(24))
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config.from_object(__name__)
Session(app)
Bootstrap(app)


def getFollowerData(username, password):
    API = InstagramAPI(username, password)
    API.login()

    API.getProfileData()
    API.LastJson.keys()

    my_id = API.LastJson['user']['pk']

    API.getUsernameInfo(my_id)
    n_media = API.LastJson['user']['media_count']

    media_ids = []
    max_id = ''
    for i in range(n_media):
        API.getUserFeed(usernameId=my_id, maxid=max_id)
        media_ids += API.LastJson['items']
        if API.LastJson['more_available'] == False:
            print("no more avaliable")
            break
        max_id = API.LastJson['next_max_id']
        print(i, "   next media id = ", max_id, "  ", len(media_ids))
        time.sleep(3)

        likers = []
        m_id = 0
        for i in range(len(media_ids)):
            m_id = media_ids[i]['id']
            API.getMediaLikers(m_id)
            likers += [API.LastJson]

        users = []
        for i in likers:
            users += map(lambda x: i['users'][x]['username'],
                         range(len(i['users'])))
        users_set = set(users)

        l_dict = {}
        for user in users_set:
            l_dict[user] = users.count(user)

        f = open(r'C:\Sophomore year\data.csv', 'w')
        f.truncate()
        f.close()
        with open(r'C:\Sophomore year\data.csv', 'w') as output:
            writer = csv.writer(output)
            for key, value in l_dict.items():
                writer.writerow([key, value])


def getRelatedContent(username, password):
    API = InstagramAPI(username, password)
    API.login()
    API.getSelfUsernameInfo()
    result = API.LastJson
    user_id = result['user']['pk']
    me = result['user']['full_name']

    API.getSelfUsersFollowing()
    result = API.LastJson
    follow_relationships = []
    for user in tqdm(result['users']):
        followed_user_id = user['pk']
        followed_user_name = user['full_name']
        follow_relationships.append((user_id, followed_user_id, me, followed_user_name))

    df_local = pd.DataFrame(follow_relationships, columns=['src_id', 'dst_id', 'src_name', 'dst_name'])
    all_user_ids_local = np.unique(df_local[['src_id', 'dst_id']].values.reshape(1, -1))

    last_year = datetime.datetime.now() - datetime.timedelta(days=365)
    now = datetime.datetime.now()
    last_result_time = now
    all_likes = []
    max_id = 0

    while last_result_time > last_year:
        API.getLikedMedia(maxid=max_id)
        results = API.LastJson
        [all_likes.append(item) for item in results['items']]
        max_id = results['items'][-1]['pk']
        last_result_time = pd.to_datetime(results['items'][-1]['taken_at'], unit='s')

    like_counts = pd.Series([i['user']['pk'] for i in all_likes]).value_counts()

    for i in tqdm(like_counts.index):
        if i in df_local['dst_id'].values:  # only count likes from people I follow
            ind = df_local[(df_local['src_id'] == user_id) & (df_local['dst_id'] == i)].index[0]
            if like_counts[i] is not None:
                df_local = df_local.set_value(ind, 'weight', like_counts[i])
    ind = df_local[df_local['weight'].isnull()].index
    df_local = df_local.set_value(ind, 'weight', 0.5)

    G = nx.from_pandas_edgelist(df_local, 'src_id', 'dst_id')
    perzonalization_dict = dict(zip(G.nodes(), [0] * len(G.nodes())))
    perzonalization_dict[user_id] = 1
    ppr = nx.pagerank(G, personalization=perzonalization_dict)

    urls = []
    taken_at = []
    num_likes = []
    page_rank = []
    users = []
    weight = []
    for user_id in tqdm(all_user_ids_local):
        API.getUserFeed(user_id)
        result = API.LastJson
        if 'items' in result.keys():
            for item in result['items']:
                if 'image_versions2' in item.keys():
                    url = item['image_versions2']['candidates'][1]['url']
                    taken = item['taken_at']
                    try:
                        likes = item['like_count']
                    except KeyError:
                        likes = 0
                    pr = ppr[item['user']['pk']]
                    user = item['user']['full_name']
                    if user != me:
                        urls.append(url)
                        taken_at.append(taken)
                        num_likes.append(likes)
                        page_rank.append(pr)
                        users.append(user)
                        weight.append(df_local[df_local['dst_name'] == user]['weight'].values[0])

    scores_df = pd.DataFrame(
        {'urls': urls,
         'taken_at': taken_at,
         'num_likes': num_likes,
         'page_rank': page_rank,
         'users': users,
         'weight': weight
         })
    # don't care about anything older than 1 week
    oldest_time = int((datetime.datetime.now() - datetime.timedelta(weeks=1)).strftime('%S'))

    scores_df = scores_df[scores_df['taken_at'] > oldest_time]

    # /1e5 to help out with some machine precision (numbers get real small otherwise)
    scores_df['time_score'] = np.exp(-(int(time.time()) - scores_df['taken_at']) / 1e5)

    scores_df['total_score'] = (np.log10(scores_df['num_likes'] + 1)
                                * scores_df['page_rank'] * scores_df['time_score']
                                * np.log(scores_df['weight'] + 1))
    top_ten = scores_df['total_score'].nlargest(10)
    top_rows = scores_df.loc[top_ten.index].values
    counter = 1
    for row in top_rows:
        imgtag = 'img'+str(counter)+'.jpg'
        response = requests.get(row[3])
        img = Image.open(BytesIO(response.content))
        img.save(r'C:\mySocial\static\images\\'+imgtag)
        counter += 1


def feedSearch(tags, username, password):
    API = InstagramAPI(username, password)
    API.login()
    interest_dict = {}
    for tag in tags:
        API.getHashtagFeed(tag)
        result = API.LastJson
        interest_dict[tag] = result

    urls = []
    num_likes = []
    tags = []
    for tag in interest_dict.keys():
        items = interest_dict[tag]['items']
        for i in items:
            if 'image_versions2' in i:
                urls.append(i['image_versions2']['candidates'][1]['url'])
                num_likes.append(i['like_count'])
                tags.append(tag)

    df_tags = pd.DataFrame(
        {'urls': urls,
         'num_likes': num_likes,
         'tag': tags
         })

    items = set()
    for i in df_tags['urls']:
        if i in items:
            continue
        items.add(i)
    items = list(items)
    counter = 1
    for item in items[:10]:
        imgtag = 'img' + str(counter) + '.jpg'
        response = requests.get(item)
        img = Image.open(BytesIO(response.content))
        img.save(r'C:\mySocial\static\images\tags\\' + imgtag)
        counter += 1


@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')


@app.route('/parse_data', methods=['POST'])
def parse_data():
    username = request.form.get('username')
    password = request.form.get('password')
    getFollowerData(username, password)
    getRelatedContent(username, password)
    session['username'] = username
    session['password'] = password
    return render_template('InstaLoggedIn.html', name=username)


@app.route('/InstaLoggedIn', methods=['GET', 'POST'])
def InstaLoggedIn():
    username = session.get('username', None)
    password = session.get('password', None)
    if flask.request.method == 'POST':
        tags = request.form.get('tag')
        feedSearch(tags, username, password)
        return redirect('http://127.0.0.1:5000/parse_data', code=302)
    return render_template('InstaLoggedIn.html')


if __name__ == '__main__':
    with app.test_request_context("/"):
        session["key"] = "value"
    app.run(debug=True)