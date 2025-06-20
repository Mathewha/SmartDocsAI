FROM opensearchproject/opensearch:2.19.0

# Install the Polish language analyzer plugin
RUN ./bin/opensearch-plugin install analysis-stempel
