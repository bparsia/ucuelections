# About this site

This site is an attempt by me, Bijan Parsia, to capture and analyse all UCU election data and present it in a form that helps us all understand UCU electoral politics.

Currently, UCU's presentation of election data is...bad. Once you have an election page, you can get the overall outcomes pretty easily, but anything deeper requries diving into multiple PDFs (some are "image" based, and there's the occasional Word doc). There's no canonical list of elections (the link to "past elections" goes to a *search*).

This is sorta fine if you just want to look up one or two things. But anything else is a nightmare. After each election, there's some discussion of turnout...but we can't easily say whether turnout is down or up or anomalous! Thus we get just-so stories about why turnout is "so low" or "down" without any proper grounding in the data.

This irks me. Even, or especially, when I do it.

Given that we (I hope) have a new website coming, I thought doing some work to model what a useful set of election pages would looking was worth 


## How it works
We have a list of "election" pages which we then scrape. We gather information from the page as well as download all the PDF (and occasionally `.doc`) reports. We then extract the data from all these sources into a set of CSV files. We do a bunch of normalisation and exception adding to get the final displayed data.

This requires a *lot* of futzing. Formats, layouts, names...really everything can vary.  I do a lot of spot checking now as I browse through, but there will need to be some cross checks implemented and manual review.

Even if the data were "clean", it's complex and irregular in a lot of ways. For example, how do you weigh casual vacancy *special elections* for turn out (especially as the highest turnout was for a special election, albeit for General Secretary). How do you want candidate "strength"? First preference winner might lose overall! Final vote includes transfers so might mistate a candidate's popularity.

For example, let's say Candidate A gets 1000 votes in the first round for UK Elected. If the quota is 600, and there's transfers, they are likely to end up with 600 "final" votes. Whereas Candidate B might have first round 100, but end up with 700 final (because the last transfer is what's recorded). All of these have information in them!

Similarly, regional seats generally require much lower quotas. Do we do percentages then? Lots to ponder!

## GenAI Declaration
I vibe coded most of this using Claude (Sonnet, from the CLI). Even so, it was tedious, my friends.

Any human oriented text like this was hand written by me.

I did the design of the Streamlit app, iteratively. Streamlit is nice both that it's easy to stand up a data oriented app and its Community Cloud makes deployment free and super easy.

You can run your own version given [the Github repo](https://github.com/bparsia/ucuelections). I have not yet tested running it from scratch. I will release the intermediate data.



