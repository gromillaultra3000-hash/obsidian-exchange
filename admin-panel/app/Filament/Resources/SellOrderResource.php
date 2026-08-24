<?php

namespace App\Filament\Resources;

use App\Filament\Resources\SellOrderResource\Pages;
use App\Models\SellOrder;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Tables;
use Filament\Tables\Table;

class SellOrderResource extends ReadOnlyResource
{
    protected static ?string $model = SellOrder::class;

    protected static ?string $navigationIcon = 'heroicon-o-arrow-down-circle';

    protected static ?string $navigationLabel = 'Продажи (sell)';

    protected static ?string $modelLabel = 'продажа';

    protected static ?string $pluralModelLabel = 'продажи';

    protected static ?string $navigationGroup = 'Торговля';

    protected static ?int $navigationSort = 2;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('currency')
                    ->label('Валюта')
                    ->disabled(),
                Forms\Components\TextInput::make('crypto_amount')
                    ->label('Сумма крипто')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('rub_amount')
                    ->label('Сумма, RUB')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('sbp_phone')
                    ->label('Телефон СБП')
                    ->disabled(),
                Forms\Components\TextInput::make('receive_address')
                    ->label('Адрес получения')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('tx_hash')
                    ->label('TX Hash')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('status')
                    ->label('Статус')
                    ->disabled(),
                Forms\Components\TextInput::make('created_at')
                    ->label('Создано')
                    ->disabled(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('id', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('id')
                    ->label('#')
                    ->sortable(),
                Tables\Columns\TextColumn::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('currency')
                    ->label('Валюта')
                    ->badge(),
                Tables\Columns\TextColumn::make('crypto_amount')
                    ->label('Крипто')
                    ->numeric(8)
                    ->sortable(),
                Tables\Columns\TextColumn::make('rub_amount')
                    ->label('RUB')
                    ->numeric(2)
                    ->sortable(),
                Tables\Columns\TextColumn::make('sbp_phone')
                    ->label('Телефон СБП')
                    ->searchable()
                    ->toggleable(),
                Tables\Columns\TextColumn::make('receive_address')
                    ->label('Адрес')
                    ->limit(20)
                    ->toggleable(),
                Tables\Columns\TextColumn::make('tx_hash')
                    ->label('TX Hash')
                    ->limit(16)
                    ->toggleable(),
                Tables\Columns\TextColumn::make('status')
                    ->label('Статус')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'completed' => 'success',
                        'confirmed' => 'info',
                        'pending' => 'gray',
                        'cancelled' => 'danger',
                        default => 'gray',
                    })
                    ->sortable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('Создано')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('status')
                    ->label('Статус')
                    ->options([
                        'pending' => 'pending',
                        'confirmed' => 'confirmed',
                        'completed' => 'completed',
                        'cancelled' => 'cancelled',
                    ]),
                Tables\Filters\SelectFilter::make('currency')
                    ->label('Валюта')
                    ->options([
                        'BTC' => 'BTC',
                        'LTC' => 'LTC',
                        'USDT' => 'USDT',
                        'ETH' => 'ETH',
                    ]),
            ])
            ->actions([
                Tables\Actions\ViewAction::make(),
            ])
            ->bulkActions([]);
    }

    public static function canCreate(): bool
    {
        return false;
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListSellOrders::route('/'),
        ];
    }
}
