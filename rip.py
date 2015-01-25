import bs4
import datetime
import logging
import os
import pickle
import urllib2
import wordpress_xmlrpc
from wordpress_xmlrpc.wordpress import WordPressPost

# If you're dealing with Unicode and this fix hasn't been integrated into
# wordpress_xmlrpc, you should appy the fix manually.
# https://github.com/maxcutler/python-wordpress-xmlrpc/issues/49

from config import *

logging.basicConfig(level=logging.DEBUG)


class WordpressRipper(object):

    def __init__(self):
        self._wp = None

    def login(self, xmlrpc_url, username, password):
        if not self._wp:
            self._wp = wordpress_xmlrpc.Client(xmlrpc_url, username, password)
        return self._wp

    def get_posts(self, params):
        posts = self._wp.call(wordpress_xmlrpc.methods.posts.GetPosts(params))
        return posts


class WordpressRipperPost(WordPressPost):

    def create_save_dir(self):
        # This should be called first otherwise we'll have problems
        self.save_to_dir = (
            '%s/%s-(%s)-%s' % (SAVE_DIR,
                               self.date.date(),
                               self.id, self.slug))
        if not os.path.exists(self.save_to_dir):
            os.makedirs(self.save_to_dir)

    def fetch_images(self, strip=False):
        self.write_log('Parsing and fetching images')
        self.images = []
        image_extensions = ['jpg', 'png', 'gif']
        soup = bs4.BeautifulSoup(self.content)
        for link in soup.find_all('a'):
            href = link.attrs['href']
            if href[-3:] in image_extensions:
                if not href.startswith(BASE_URL):
                    # If we have a relative url, probably /wp-content
                    href = '%s/%s' % (BASE_URL, href)

                self.write_log("Image found: %s" % (href))
                filename = href.split('/')[-1]
                try:
                    resource = urllib2.urlopen(href)
                except urllib2.HTTPError, ex:
                    error_string = (
                        'Error fetching image: %s, %s' % (href, ex.message))
                    self.write_error(error_string)
                    continue

                raw_img = resource.read()
                self.images.append(
                    {'filename': filename,
                     'raw_img': raw_img,
                     'original_url': href
                     })
                poss_div = link.find_parent()
                if ((poss_div.name == 'div') and
                        (poss_div.attrs.get('align') == 'center')):
                    self.write_log("Removing centered img: %s" % poss_div)
                    poss_div.extract()
                link.extract()
        for img in soup.find_all('img'):
            src = img.attrs['src']
            # TODO: DRY
            self.write_log("Image found: %s" % (src))
            filename = src.split('/')[-1]
            try:
                resource = urllib2.urlopen(src)
            except urllib2.HTTPError, ex:
                error_string = (
                    'Error fetching image: %s, %s' % (src, ex.message))
                self.write_error(error_string)
                continue

            raw_img = resource.read()
            self.images.append({'filename': filename,
                                'raw_img': raw_img,
                                'original_url': src})
            poss_div = link.find_parent()
            if (poss_div and (poss_div.name == 'div')):
                self.write_log("Removing div: %s" % poss_div)
                poss_div.extract()
            img.extract()

        self.write_log('Saved cleaned post body')
        self.clean_content = soup.__unicode__()

    def save_images_to_directory(self):
        for img in self.images:
            self.write_log('Saving image %s' % img.get('filename'))
            self.write_to_file(img.get('filename'), img.get('raw_img'))

    def save_tags(self):
        tags = []
        for term in self.terms:
            tags.append(term.name)
        self.write_log('Saving tags: %s' % ','.join(tags).encode('utf8'))
        self.write_to_file('tags.csv', ','.join(tags).encode('utf8'))

    def save_title(self):
        self.write_log('Saving title: %s' % self.title.encode('utf8'))
        self.write_to_file('title.txt', self.title.encode('utf8'))

    def save_body(self):
        try:
            if self.clean_content:
                self.write_log('Saving cleaned body')
                self.write_to_file('body.txt',
                                   self.clean_content.encode('utf8'))
            self.write_log('Saving original body')
            self.write_to_file('original_body.txt',
                               self.content.encode('utf8'))
        except UnicodeDecodeError, ex:
            self.write_error("Unicode failure: %s" % ex.message)
            raise

    def write_to_file(self, filename, content, mode="wb"):
        output = open('%s/%s' % (self.save_to_dir, filename), mode)
        output.write(content)
        output.close()

    @property
    def is_done(self):
        return os.path.exists('%s/%s' % (self.save_to_dir, 'done'))

    def write_log(self, log_message):
        message = '%s %s' % (datetime.datetime.now(), log_message)
        logging.info(message)
        self.write_to_file('results.log', "%s\n" % message, "a+")

    def write_error(self, error_string):
        err_string = '%s %s' % (datetime.datetime.now(), error_string)
        logging.error(err_string)
        self.write_to_file('errors.log', "%s\n" % err_string, "a+")

    def mark_done(self):
        self.write_log('Marking done')
        self.write_to_file('done', datetime.datetime.now().isoformat())

    def dump_object(self):
        fp = open("%s/%s" % (self.save_to_dir, 'post_object'), "w+")
        pickle.dump(self, fp)


def load_post_object(filepath):
    return pickle.load(open(filepath))


if __name__ == '__main__':
    logging.info('Starting execution...')
    wp = WordpressRipper()
    wp.login(WP_URL, USER, PASS)
    # This has only been tested with 550 actual posts, YMMV for more.
    # If you want to grab anything other than published posts,
    # change post_status
    params = {'number': 600,
              'post_status': 'publish',
              'orderby': 'post_date',
              'order': 'ASC'}
    logging.info('Fetching %s posts: %s' % (params.get('number'), params))
    posts = wp.get_posts(params)
    logging.info('Posts found: %u' % len(posts))
    logging.info(posts)

    for post in posts:
        logging.info(post)
        post.__class__ = WordpressRipperPost
        post.create_save_dir()
        if not post.is_done:
            post.save_title()
            post.fetch_images(strip=True)
            for img in post.images:
                logging.info(img.get('filename'))
            post.save_images_to_directory()
            post.save_tags()
            post.save_body()
            post.dump_object()
            post.mark_done()
