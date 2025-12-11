# templates.py

HOME_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 助手</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; }
        h1, h2 { color: #333; }
        a { color: #007BFF; text-decoration: none; }
        a:hover { text-decoration: underline; }
        textarea { width: 100%; padding: 10px; font-size: 16px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        input[type="submit"] { background-color: #007BFF; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        input[type="submit"]:hover { background-color: #0056b3; }
        .status-box { padding: 15px; margin-top: 20px; border-radius: 4px; }
        .success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }

        /* --- 聊天界面样式 --- */
        #chat-container {
            height: 400px;
            overflow-y: scroll;
            border: 1px solid #ccc;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 10px;
            background-color: #fafafa;
        }
        .chat-message {
            margin-bottom: 10px;
            padding: 8px 12px;
            border-radius: 18px;
            max-width: 80%;
            word-wrap: break-word;
        }
        .user-message {
            background-color: #007BFF;
            color: white;
            margin-left: auto;
            text-align: left;
        }
        .model-message {
            background-color: #e9e9e9;
            color: #333;
            margin-right: auto;
            text-align: left;
        }
        .chat-input-area {
            display: flex;
        }
        #chat-input {
            flex-grow: 1;
            padding: 10px;
            border-radius: 4px 0 0 4px;
            border: 1px solid #ccc;
            font-size: 16px;
        }
        #send-button {
            padding: 10px 15px;
            border: none;
            background-color: #007BFF;
            color: white;
            cursor: pointer;
            border-radius: 0 4px 4px 0;
            font-size: 16px;
        }
        #send-button:disabled {
            background-color: #aaa;
        }
        #chat-status {
            font-size: 0.9em;
            color: #555;
            height: 1.2em;
        }

        /* [!!! Popup (Modal) 样式 - 保留用于地点搜索结果 !!!] */
        .modal {
            display: none; /* 默认隐藏 */
            position: fixed; 
            z-index: 100; 
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: auto; 
            background-color: rgba(0,0,0,0.5); 
        }
        .modal-content {
            background-color: #fefefe;
            margin: 10% auto; 
            padding: 20px;
            border: 1px solid #888;
            width: 90%;
            max-width: 700px;
            border-radius: 8px;
            position: relative;
        }
        .close-button {
            color: #aaa;
            position: absolute;
            top: 10px;
            right: 20px;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close-button:hover,
        .close-button:focus {
            color: black;
        }
        #modal-body {
            max-height: 60vh;
            overflow-y: auto;
        }
        .place-card {
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 15px;
        }
        .place-card h3 {
            margin-top: 0;
            color: #007BFF;
        }
        .place-card p {
            margin: 5px 0;
            font-size: 0.95em;
        }
        .place-card .price-level {
            font-weight: bold;
            color: #28a745;
        }
        /* [!!! Popup 样式结束 !!!] */

    </style>
</head>
<body>
    <h1>AI 助手 (仅聊天和地点/天气)</h1>

    <h2>AI 助手</h2>
    <div id="chat-container">
        <div class="chat-message model-message">
            你好！我是您的地点和天气助手。您可以对我说：“吉隆坡附近有什么好吃的？”或“今天的天气怎么样？”
        </div>
    </div>
    <div id="chat-status"></div>
    <div class="chat-input-area">
        <input type="text" id="chat-input" placeholder="输入消息...">
        <button id="send-button">发送</button>
    </div>

    <div id="places-modal" class="modal">
        <div class="modal-content">
            <span class="close-button">&times;</span>
            <h2>为您找到的地点</h2>
            <div id="modal-body">
                </div>
        </div>
    </div>
    <script>
        if (document.getElementById('chat-input')) {
            const chatInput = document.getElementById('chat-input');
            const sendButton = document.getElementById('send-button');
            const chatContainer = document.getElementById('chat-container');
            const chatStatus = document.getElementById('chat-status');
            let conversationHistory = [];
            let userCoordinates = null;

            // [!!! Modal 变量 !!!]
            const modal = document.getElementById('places-modal');
            const modalBody = document.getElementById('modal-body');
            const closeModal = document.getElementsByClassName('close-button')[0];
            // [!!! Modal 变量结束 !!!]


            conversationHistory.push({
                'role': 'model',
                'parts': ['你好！我是您的地点和天气助手。您可以对我说：“吉隆坡附近有什么好吃的？”或“今天的天气怎么样？”']
            });

            function getGeolocation() {
                // ... (此函数保持不变) ...
                if ('geolocation' in navigator) {
                    chatStatus.textContent = '正在请求您的位置...';
                    navigator.geolocation.getCurrentPosition(
                        (position) => {
                            userCoordinates = {
                                latitude: position.coords.latitude,
                                longitude: position.coords.longitude
                            };
                            console.log('GPS 坐标已获取:', userCoordinates);
                            chatStatus.textContent = '已获取您的精确位置。';
                        },
                        (error) => {
                            console.warn('GPS 获取失败:', error.message);
                            if (error.code === 1) {
                                chatStatus.textContent = '您已拒绝位置授权。将使用 IP 地址进行粗略定位。';
                            } else {
                                chatStatus.textContent = '无法获取您的位置。将使用 IP 地址进行粗略定位。';
                            }
                        }
                    );
                } else {
                    console.warn('浏览器不支持 GPS 地理位置。');
                    chatStatus.textContent = '浏览器不支持 GPS。将使用 IP 地址进行粗略定位。';
                }
            }
            getGeolocation();

            function addMessageToUI(message, role) {
                const msgDiv = document.createElement('div');
                msgDiv.classList.add('chat-message');
                msgDiv.classList.add(role === 'user' ? 'user-message' : 'model-message');
                msgDiv.textContent = message;
                chatContainer.appendChild(msgDiv);
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }

            // [!!! 关闭 Modal 的逻辑 !!!]
            closeModal.onclick = function() {
                modal.style.display = "none";
            }
            window.onclick = function(event) {
                if (event.target == modal) {
                    modal.style.display = "none";
                }
            }
            
            // [!!! 用于构建和显示 Popup 的函数 - 保留 !!!]
            function displayPlacesPopup(places) {
                // 1. 清空旧内容
                modalBody.innerHTML = ''; 

                if (!places || places.length === 0) {
                     modalBody.innerHTML = '<p>抱歉，未能找到任何地点的详细信息。</p>';
                } else {
                    // 2. 为每个地点创建卡片
                    places.forEach(place => {
                        const card = document.createElement('div');
                        card.classList.add('place-card');
                        
                        let html = `<h3>📍 ${place.name || '未知名称'}</h3>`;
                        html += `<p>🗺️ <strong>地址:</strong> ${place.address || 'N/A'}</p>`;
                        html += `<p>⭐ <strong>评分:</strong> ${place.rating || 'N/A'} / 5</p>`;
                        
                        let openStatus = "营业状态未知";
                        if (place.is_open_now === true) {
                            openStatus = '<span style="color: green; font-weight: bold;">正在营业</span>';
                        } else if (place.is_open_now === false) {
                            openStatus = '<span style="color: red; font-weight: bold;">已关闭</span>';
                        }
                        html += `<p>⏰ <strong>营业状态:</strong> ${openStatus}</p>`;
                        
                        html += `<p>📞 <strong>电话:</strong> ${place.phone || 'N/A'}</p>`;
                        
                        if (place.website && place.website !== 'N/A') {
                             html += `<p>🌐 <strong>网站:</strong> <a href="${place.website}" target="_blank">访问网站</a></p>`;
                        }
                        
                        // 价格
                        if (place.price_level && place.price_level !== 'N/A' && place.price_level !== 'PRICE_LEVEL_UNSPECIFIED') {
                            let price = place.price_level.replace('PRICE_LEVEL_', '');
                            html += `<p>💰 <strong>价格:</strong> <span class="price-level">${price}</span></p>`;
                        }

                        // 评论
                        if (place.review_list && place.review_list[0] !== 'N/A') {
                             html += `<p>💬 <strong>热门评论:</strong> "${place.review_list[0]}"</p>`;
                        }

                        card.innerHTML = html;
                        modalBody.appendChild(card);
                    });
                }
                
                // 3. 在聊天中添加一条通用消息
                addMessageToUI('为您找到了以下几个地点，请在弹窗中查看详情！', 'model');
                
                // 4. 显示 Modal
                modal.style.display = "block";
            }


            // [!!! 修改：sendMessage 函数 - 移除 history 中的 credentials_dict !!!]
            async function sendMessage() {
                const message = chatInput.value.trim();
                if (!message) return;
                addMessageToUI(message, 'user');
                chatInput.value = '';
                chatInput.disabled = true;
                sendButton.disabled = true;
                chatStatus.textContent = 'AI 正在思考...';
                try {
                    const response = await fetch('/chat_message', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            message: message,
                            history: conversationHistory,
                            coordinates: userCoordinates
                            // 移除 credentials_dict
                        })
                    });
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || `HTTP 错误: ${response.status}`);
                    }
                    const data = await response.json();
                    
                    // [!!! 关键逻辑：检查魔法字符串 !!!]
                    if (data.reply.startsWith('POPUP_DATA::')) {
                        console.log("检测到 POPUP_DATA，正在解析...");
                        const jsonString = data.reply.substring('POPUP_DATA::'.length);
                        try {
                            const placesData = JSON.parse(jsonString);
                            // 调用新函数来显示 Popup
                            displayPlacesPopup(placesData);
                            // 我们必须手动将AI的“魔法回复”添加到历史记录中，以便AI保持上下文
                            conversationHistory = data.history;
                        } catch (parseError) {
                            console.error('解析地点 JSON 失败:', parseError);
                            addMessageToUI('抱歉，我找到了地点，但在显示它们时出错了。', 'model');
                        }
                    } else {
                        // 正常的文本回复
                        addMessageToUI(data.reply, 'model');
                        conversationHistory = data.history;
                    }
                    // [!!! 修改结束 !!!]
                    
                } catch (error) {
                    console.error('聊天时发生错误:', error);
                    addMessageToUI(`错误: ${error.message}`, 'model');
                } finally {
                    chatInput.disabled = false;
                    sendButton.disabled = false;
                    if (chatStatus.textContent === 'AI 正在思考...') {
                         chatStatus.textContent = userCoordinates ? '已获取您的精确位置。' : '无法获取您的精确位置。';
                    }
                    chatInput.focus();
                }
            }
            sendButton.addEventListener('click', sendMessage);
            chatInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }
    </script>
    </body>
</html>
"""