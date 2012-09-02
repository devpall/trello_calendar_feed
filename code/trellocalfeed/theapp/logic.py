import time
import random
import string
import hashlib
import datetime

import pytz
import trello
import icalendar

import models

API_KEY = "9cf5a88e6a3a9897d59e55bfc327b5d5"

SALT_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()_+{}[]"
SALT_LENGTH = 16

def _create_salt_and_url(user_name):
    """
    Create a random salt and url hash from the given username. This is basically giving us some random long
    string - security 
    """
    salt = "".join([random.choice(SALT_ALPHABET) for i in xrange(SALT_LENGTH)])
    url = hashlib.sha512(user_name + salt).hexdigest()
    return salt, url

def get_or_create_feed_in_db(token, user_name):
    """
    Either get the feed model for the user_name given or create it if it doesn't exist.
    """
    now = time.time()
    try:
        feed_model = models.Feed.objects.get(user_name=user_name, user_token=token)
    except models.Feed.DoesNotExist:
        try:
            feed_model = models.Feed.objects.get(user_name=user_name)
            feed_model.token = token
        except models.Feed.DoesNotExist:
            salt, url = _create_salt_and_url(user_name)
            feed_model = models.Feed(user_token=token, user_name=user_name, created=now, last_access=now, url=url, salt=salt)
    
    feed_model.last_access = now
    feed_model.save()
    
    return feed_model

def get_or_create_user(token, username, userid):
    """
    Either get the user model that corresponds to the given user id or create a new user model.
    """
    now = time.time()
    try:
        user_model = models.FeedUser.objects.get(trello_member_id=userid)
    except models.FeedUser.DoesNotExist:
        salt, url = _create_salt_and_url(username)
        user_model = models.FeedUser(user_name=username, user_token=token, url=url, trello_member_id=userid, created=now)
    
    user_model.last_access = now
    user_model.save()
    
    return user_model
    
def create_calendar_from_feed(feed):
    """
    Create an ical object from the cards from the feed given.
    """
    client = trello.client.Trello(API_KEY, feed.feed_user.user_token)
    
    card_list = []    
    
    boards = client.list_boards()
    board_ids = feed.boards.all().values_list("board_id")
    board_ids = [i[0] for i in board_ids]
    
    for board in boards:
        if board.id not in board_ids:
            continue
        
        cards = board.list_cards()
        for card in cards:
            if (feed.only_assigned) and (feed.feed_user.trello_member_id not in card.assignees):
                continue            
            
            if card.due != None:
                card_start_time = card.due
                start_time = datetime.datetime.strptime(card_start_time, "%Y-%m-%dT%H:%M:%S.000Z")
                if start_time > datetime.datetime.now():
                    card_list.append(card)
                    
    return create_calendar_from_cards(card_list, feed)
    

def get_all_board_names(token):
    """
    Get a list of all board names of the user whose token is given.
    """
    boards = get_all_boards(token)
    board_names = []
    for board in boards:
        board_names.append(board.name)
    
    return board_names
    

def get_all_boards(token):
    client = trello.client.Trello(API_KEY, token)
    boards = client.list_boards()
    
    for board in boards:
        board.fetch()
    
    return boards


def create_feed(user, is_only_assigned, all_day_meeting, meeting_length, boards):
    salt, url = _create_salt_and_url(user.user_name)

    now = time.time()
    feed_model = models.Feed(feed_user=user, salt=salt, url=url, only_assigned=is_only_assigned,
                             is_all_day_event=all_day_meeting, event_length=meeting_length,
                             last_access=now, created=now)
    
    feed_model.save()
    
    client = trello.client.Trello(API_KEY, user.user_token)
    for board in boards:
        board_id = board.replace("checkbox_board_", "")
        try:
            board_model = models.Board.objects.get(board_id=board_id, )
        except models.Board.DoesNotExist:
            board_from_trello = trello.client.Board(client, board_id)
            board_from_trello.fetch()
            board_name = board_from_trello.name
            
            board_model = models.Board(board_id=board_id, name=board_name)
            board_model.save()
            
        feed_model.boards.add(board_model)
    
    return feed_model
    


def create_calendar_from_cards(card_list, feed):
    """
    Create an ical object from the card list given and return it/
    """
    #Create calendar object:
    calendar = _create_calendar()
    
    #Create event for each card:
    for card in card_list:
        event = _create_event_from_card(card, feed)
        calendar.add_component(event)
    
    return calendar
        
def _create_calendar():
    cal = icalendar.Calendar()
    cal.add("prodid", "-//sveder.com/trello_to_ical//EN")
    cal.add("version", "2.0")
    return cal

def _create_event_from_card(card, feed):
    card_start_time = card.due
    start_time_struct = time.strptime(card_start_time, "%Y-%m-%dT%H:%M:%S.000Z")
    start_time = datetime.datetime(*(start_time_struct[:6]), tzinfo=pytz.utc)
    if feed.is_all_day_event:
        end_time = start_time + datetime.timedelta(days=1)
    else:
        end_time = start_time + datetime.timedelta(minutes=feed.event_length)
    
    event = icalendar.Event()
    #hackity hack to maybe not add new line to summary:
    summary = card.name[:50] + "..."
    event.add("summary", "Trello Item: %s" % summary)
    event.add('DESCRIPTION', card.url)
    
    event.add('dtstart', start_time)
    event.add('dtend', end_time)
    #event.add('dtstamp', start_time)
    event["uid"] = "%strello_to_ical" % card.id
    
    return event
    