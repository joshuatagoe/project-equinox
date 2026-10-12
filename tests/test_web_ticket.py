"""feat-14 commit 2: the order ticket says what it does (user, 2026-10-12).

"what does price my order look/do? ... its also not clear what it does, or what budget does": the
ticket says what comparing does and that nothing is bought, what the budget is for, and what the
contracts pay.
"""

from test_web_app import COV_2_1, scores_app, words


def ticket(tmp_path, query):
    return words(scores_app(tmp_path).respond("/bet", f"m={COV_2_1}&{query}"))


def test_the_ticket_says_what_comparing_does_and_that_nothing_is_bought(tmp_path):
    text = ticket(tmp_path, "side=YES&quantity=10")
    assert "checks how many contracts each venue is selling at each price" in text
    assert "Nothing is bought." in text and "Compare venues" in text


def test_the_budget_says_what_it_does(tmp_path):
    text = ticket(tmp_path, "side=YES&quantity=10")
    assert "Most you'd spend ($), optional" in text
    assert "A venue that would cost more is ruled out." in text


def test_the_answer_says_what_the_contracts_pay(tmp_path):
    yes = ticket(tmp_path, "side=YES&quantity=10")
    assert "If this happens, your 10 YES contracts pay $10.00; if not, they pay nothing." in yes
    no = ticket(tmp_path, "side=NO&quantity=10")
    paid = "If this doesn't happen, your 10 NO contracts pay $10.00; if it does, they pay nothing."
    assert paid in no
