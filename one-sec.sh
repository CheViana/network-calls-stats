while true
do
    echo "find Python's open sockets"
    lsof -p process-id | grep TCP
sleep 1
done