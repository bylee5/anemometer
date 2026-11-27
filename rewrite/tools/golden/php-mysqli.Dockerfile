# PHP CLI with the extensions the original application needs (for e2e.sh).
FROM php:7.4-cli
RUN docker-php-ext-install mysqli bcmath
